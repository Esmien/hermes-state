#!/usr/bin/env python3
"""Prove the Open WebUI -> Open Terminal integration end-to-end (host-side, stdlib only).

Checks, in order:
  1. admin login (OWUI_ADMIN_PASSWORD from the signup-approver env, never printed);
  2. /api/config feature flags: enable_direct_integrations / enable_terminal_servers;
  3. a real chat request with a unique marker command through `run_command`;
  4. evidence that Open Terminal actually executed it (its own /execute log);
  5. deletes the throwaway chat it created.

Usage:
    python3 probe-owui-terminal.py [--model deepseek-v41-flash] [--terminal-id UUID] [--keep]

Exit code 0 only when flags are on and Open Terminal received an /execute request.
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get('OWUI_BASE', 'http://127.0.0.1:8080')
ADMIN_EMAIL = os.environ.get('OWUI_ADMIN_EMAIL', 'black.walf16@gmail.com')
APPROVER_ENV = pathlib.Path('/root/.config/owui-signup-approver/env')


def admin_password():
    pw = os.environ.get('OWUI_ADMIN_PASSWORD')
    if pw:
        return pw
    text = APPROVER_ENV.read_text()
    m = re.search(r'OWUI_ADMIN_PASSWORD=(\S+)', text)
    if not m:
        sys.exit(f'OWUI_ADMIN_PASSWORD not found in {APPROVER_ENV}')
    return m.group(1)


def call(path, payload=None, token=None, method=None, timeout=120):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data, headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors='replace')


def terminal_connection_id():
    """First terminal connection id from the config table (read-only, host psql)."""
    out = subprocess.run(
        ['sudo', '-u', 'postgres', 'psql', '-d', 'webui_db', '-Atc',
         "select value->0->>'id' from config where key='terminal_server.connections'"],
        capture_output=True, text=True, timeout=30,
    )
    return out.stdout.strip() or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='deepseek-v41-flash')
    ap.add_argument('--terminal-id', default=None)
    ap.add_argument('--keep', action='store_true', help='keep the probe chat')
    args = ap.parse_args()

    code, body = call('/api/v1/auths/signin', {'email': ADMIN_EMAIL, 'password': admin_password()})
    if code != 200:
        sys.exit(f'login failed: HTTP {code}: {body[:200]}')
    token = json.loads(body)['token']

    code, body = call('/api/config', token=token)
    feats = (json.loads(body).get('features') or {}) if code == 200 else {}
    direct = feats.get('enable_direct_integrations')
    terminals = feats.get('enable_terminal_servers')
    print(f'features: direct_integrations={direct} terminal_servers={terminals}')
    if not (direct and terminals):
        print('FAIL: ENABLE_DIRECT_INTEGRATIONS is off (env) or direct.integrations.enable=false (config table)')
        return 1

    tid = args.terminal_id or terminal_connection_id()
    if not tid:
        print('FAIL: no terminal_server.connections row in webui_db')
        return 1

    code, body = call('/api/v1/chats/new', {'chat': {'title': 'terminal probe'}}, token=token)
    if code != 200:
        sys.exit(f'chat create failed: HTTP {code}: {body[:200]}')
    cid = json.loads(body)['id']
    marker = 'OWUI_TERMINAL_' + str(int(time.time()))

    payload = {
        'model': args.model,
        'stream': True,
        'chat_id': cid,
        'id': cid,
        'session_id': cid,
        'terminal_id': tid,
        'tool_ids': [],
        'features': {},
        'params': {},
        'messages': [{'role': 'user', 'content':
                      f'Выполни в терминале команду `echo {marker}` инструментом run_command и покажи вывод дословно.'}],
    }
    before = subprocess.run(['docker', 'logs', 'open-terminal', '--since', '2m'],
                            capture_output=True, text=True, timeout=60).stderr
    code, body = call('/api/chat/completions', payload, token=token, timeout=300)
    print(f'completion: HTTP {code} (marker {marker})')

    time.sleep(5)
    after = subprocess.run(['docker', 'logs', 'open-terminal', '--since', '2m'],
                           capture_output=True, text=True, timeout=60).stderr
    new_exec = [ln for ln in after.splitlines() if '/execute' in ln and ln not in before]
    print('open-terminal /execute evidence:', len(new_exec))
    for ln in new_exec[-4:]:
        print('  ', ln.strip())

    if not args.keep:
        call(f'/api/v1/chats/{cid}', token=token, method='DELETE')
        print('probe chat deleted')

    if new_exec:
        print('PASS: terminal executed the tool call end to end')
        return 0
    print('INCONCLUSIVE: no /execute seen — check ENABLE_DIRECT_INTEGRATIONS, terminal_id and open-terminal health')
    return 1


if __name__ == '__main__':
    sys.exit(main())

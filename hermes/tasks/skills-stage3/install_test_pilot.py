"""Install isolated personal catalogue pilot for the authorized Test account only."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ID = 'personal_skill_catalog_pilot'
TEST = '695924f7-9a9b-4ba4-bc54-a5bc2a440d56'
BASE = 'http://127.0.0.1:8080'
source = Path(__file__).with_name('pilot_tool.py').read_text(encoding='utf-8')
sql = "select k.key from api_key k join \"user\" u on u.id=k.user_id where u.role='admin' limit 1"
key = subprocess.run(['sudo', '-u', 'postgres', 'psql', '-d', 'webui_db', '-X', '-A', '-t', '-c', sql], capture_output=True, text=True, check=True).stdout.strip()
if not key:
    raise RuntimeError('No existing admin API key; no credentials generated')

def call(method, path, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError('API request failed: HTTP ' + str(exc.code)) from exc

payload = {
    'id': ID,
    'name': 'Личные скиллы — пилот Test',
    'content': source,
    'meta': {'description': 'Пилот каталога личных скиллов только для Test'},
    'access_grants': [{'principal_type': 'user', 'principal_id': TEST, 'permission': 'read'}],
    'commit_message': 'Isolated catalogue pilot for Test',
}
created = call('POST', '/api/v1/tools/create', payload)
if created.get('id') != ID:
    raise RuntimeError('Creation response differs from requested ID; verify manually')
readback = call('GET', '/api/v1/tools/id/' + ID)
if readback.get('content') != source:
    raise RuntimeError('Read-back content differs; pilot remains installed and requires review')
grants = readback.get('access_grants') or []
if len(grants) != 1 or any(grants[0].get(k) != v for k, v in payload['access_grants'][0].items()):
    raise RuntimeError('Grant mismatch; pilot remains installed and requires review')
print('Created pilot and verified exact source + sole Test read grant; sha256:', hashlib.sha256(source.encode()).hexdigest())

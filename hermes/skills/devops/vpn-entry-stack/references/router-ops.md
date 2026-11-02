# Router ops: apply, rebuild, probe

Everything that touches the live routing goes through three entry points, in this order:
config edit -> apply -> verify by dialling a path, never by reading the file back.

## vpn-cfg (config edit / apply / rollback)

`/usr/local/bin/vpn-cfg` (source: this skill's `scripts/vpn-cfg.sh`, install with
`install -m 755 scripts/vpn-cfg.sh /usr/local/bin/vpn-cfg`):

| command | what it does |
|---|---|
| `vpn-cfg status` | inbound/outbound counts, default route, container state and restarts |
| `vpn-cfg show [filter]` | pretty-printed `config.json` |
| `vpn-cfg edit` | timestamped backup into `/root/vpn-router/backups/`, then `$EDITOR` |
| `vpn-cfg apply` | JSON validation -> backup -> `docker restart vpn-router` -> health check |
| `vpn-cfg rollback` | copy newest backup over `config.json` and restart |
| `vpn-cfg backups` | last ten backups |

`apply` probes `/general`, `/france`, `/fi` through nginx with
`--resolve <host>:8443:127.0.0.1`, so it works even when DNS or the certificate is off.
Expected healthy answer is **400** (the inbound is a WebSocket path and the probe sends no
upgrade header) - treat only 000/404/502 as failure, and let the built-in rollback fire.

Rule: never `docker restart vpn-router` by hand after editing the config. The restart alone
hides a broken rule; `vpn-cfg apply` proves the three routes still answer and reverts if not.

## Config inventory

- `/root/vpn-router/config.json` (0600) - Xray inbounds, outbounds, routing rules.
- `/root/vpn-router/brand.json` - public host, ports, path/upstream map, `legacy_hosts`.
- `/root/vpn-router/make_sub.py` - subscription rendering (three formats, two kinds).
- `/root/vpn-router/relay_nodes.json`, `whitelist_links.json` (0600) - imported relay map and
  raw whitelist links; both carry provider credentials, never commit them.
- `/root/vpn-router/backups/` - `vpn-cfg` snapshots.

## Rebuild on a fresh server

```bash
bash assets/vpn/scripts/deploy.sh vpn.example.com mail@example.com
python3 /root/vpn-router/import_sub.py <sub-file> [indices of dead nodes]
```

`deploy.sh` is idempotent: nginx + stream module + certbot, scripts into `/root/vpn-router`,
config from `config.template.json` with a freshly generated UUID, certificate via webroot,
`vpn-router` container (`--network host`), rendered vhosts, subscriptions, health check.

There is no panel step and no 3x-ui anywhere in this path - the whole entry is one container
plus flat files, which is exactly what makes it portable.

## make_template.py - keep the template truthful

The repo's `config.template.json` is generated, not hand-maintained:

```bash
python3 /root/vpn-router/make_template.py            # live config -> assets/vpn/router/config.template.json
```

It keeps only the base tags (`ws-in`, `in-general`, `in-france`, `in-test`, `in-fi`, and
`fr/fi/direct/blocked`), drops every imported relay (`in-p*`, `p*`), forces listens to
`127.0.0.1`, trims rules that point at removed tags, and masks `id`/`password` as
`<VLESS_UUID>`/`<PASSWORD>`. Run it after any structural change, then commit - the recovery
repo must equal the live host, so a stale template is a real defect, not cosmetic drift.

Two consequences worth knowing: the template carries only `direct`/`blocked` outbounds
(exits are added later by `import_sub.py`, each with its own credentials), and re-rendering
from a host whose config still holds placeholder UUIDs would bake the placeholder into the
template - check that `brand.json`/`config.json` on the host are the real ones first.

## Probes run on the host

`/usr/local/bin/xray` is the same core the container runs; `probe_sub.py` and
`test_whitelist.py` shell out to it directly (`xray run -c <work>/n<i>.json & pid=$!` ...
`kill $pid`), so no container is needed for measurement. When the binary is missing, copy it
out of any running xray container rather than downloading a build:

```bash
docker cp <container>:/app/bin/xray-linux-amd64 /usr/local/bin/xray && chmod 755 /usr/local/bin/xray
xray version
```

Kill the child by PID, never `pkill -f <cfg>.json` - the pattern also matches the shell that
runs the loop and the probe dies after the first node.

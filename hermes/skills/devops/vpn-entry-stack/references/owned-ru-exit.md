# Owned RU exit (VLESS + Reality) replacing reseller relays

When the RU scenario must stop depending on someone else's flapping Moscow node, the answer is an
owned Russian VPS carrying a Reality inbound that only our entry may dial. Cheap (a 1 vCPU / 2 GB
/ 20 GB KVM is 2-5x more than enough: xray holds ~120 MB and a few percent of one core), and it
removes the reseller from the critical path for gosuslugi / banks / marketplaces.

## 0. Vet and test the box before wiring anything

- Provider check: `whois <domain>` for the legal entity and domain age, then `whois <ip>` for
  `netname`/`country` and `whois -h whois.cymru.com " -v <ip>"` for the ASN. Own AS + own DC is
  the good case; a small DC that was recently DDoSed is a reason to keep a second option, not to
  refuse. Independent reviews matter more than the catalogue listings on hosting-comparison sites.
- The configuration must include a **dedicated public IPv4** (not behind CGNAT). Ubuntu **Server**
  ISO, not desktop: the desktop image eats ~8 GB and 1.5 GB RAM for a GUI nobody opens.
- The one thing that can kill the whole idea is IP reputation, and it is only testable after boot:

```bash
for u in http://www.gosuslugi.ru https://www.gosuslugi.ru https://www.sberbank.ru \
         https://www.tbank.ru https://www.vtb.ru https://www.alfabank.ru https://www.ozon.ru; do
  printf '%-32s ' "$u"; curl -sk -o /dev/null -w '%{http_code} %{time_total}s\n' --max-time 15 "$u"
done
```

  Healthy: gosuslugi `200` over https / `307` over http, Sber `200` (or `302` on `online.`),
  T-Bank/VTB/Alfa `200`, Ozon `307`. `wildberries.ru` answering `498` is WB's own fingerprint
  challenge and says nothing bad. `alfabank.ru` returns `000` to a bare curl and `200` with a
  browser `-A` — always retry with a UA before declaring a block. A datacenter address that
  gosuslugi refuses cannot be fixed by any config: say so and stop.
- Record the latency from the entry (`ping` = the extra hop .ru traffic will pay, ~40 ms Tallinn→
  Moscow is normal) and the disk (`dd if=/dev/zero of=/tmp/t bs=1M count=128 conv=fdatasync`).

## 1. Binary — copy, do not download

The entry already runs the exact xray version we want on both sides:

```bash
docker cp vpn-router:/usr/local/bin/xray ./xray-bin
scp -i <key> ./xray-bin root@<ru-ip>:/usr/local/bin/xray && ssh root@<ru-ip> 'chmod +x /usr/local/bin/xray'
```

## 2. Keys and identifiers (on the RU box)

```bash
xray x25519                 # PrivateKey / Password (PublicKey) / Hash32
cat /proc/sys/kernel/random/uuid
openssl rand -hex 8         # shortId
```

## 3. Server config `/usr/local/etc/xray/config.json`

VLESS + Reality, port 443, `dest`/`serverNames` a real TLS site that answers from Russia, sniffing
on, a single `freedom` outbound:

```json
{"inbounds":[{"listen":"0.0.0.0","port":443,"protocol":"vless",
  "settings":{"clients":[{"id":"<uuid>","flow":""}],"decryption":"none"},
  "streamSettings":{"network":"tcp","security":"reality","realitySettings":{
    "show":false,"dest":"www.microsoft.com:443","xver":0,
    "serverNames":["www.microsoft.com"],"privateKey":"<priv>","shortIds":["<sid>"]}},
  "sniffing":{"enabled":true,"destOverride":["http","tls"],"routeOnly":false}}],
 "outbounds":[{"protocol":"freedom","tag":"direct","settings":{"domainStrategy":"UseIPv4"}}]}
```

`chmod 600` the file (it holds the private key), `xray run -test -c …` before starting, then a
plain systemd unit (`ExecStart=/usr/local/bin/xray run -c /usr/local/etc/xray/config.json`,
`Restart=always`, `LimitNOFILE=65535`).

## 4. Firewall — the inbound is not public

```bash
ufw allow 22/tcp                                  # first, or you lock yourself out
ufw allow from <entry-ip> to any port 443 proto tcp
ufw --force enable
```

Only the entry may dial it; a Reality inbound on 443 with no allowlist is an open proxy.

## 5. Wire it into the entry

- Add an outbound `ru1` **before** `direct`: `vless` → `<ru-ip>:443`, user `<uuid>`,
  `streamSettings.realitySettings` = `{serverName, publicKey, shortId, fingerprint: "chrome", spiderX: "/"}`.
- Put the tag into the RU group: `scenario_override.json` → `{"bal-ru": ["ru1", "direct"]}` and the
  same list in `GROUPS`/`PREFERENCE` of `scenario_routes.py`, then `vpn-cfg apply`. The overseer
  keeps the selector there and no longer invests provider relays in the RU path.
- `observatory.subjectSelector` must include `ru1`, or `leastPing` has no data for it and `.ru`
  traffic hangs (see `scenario-routes.md`).

## 6. Verify

1. Direct dial from the entry (throwaway client, `reality` outbound, socks) → `ipinfo.io/ip` returns
   the RU box address. This proves key + allowlist + Reality before any routing is involved.
2. Through `/general`: `gosuslugi.ru` `200` in ~0.2-0.4 s, `ozon.ru` `307`, `ya.ru` `302`,
   `wildberries.ru` `498`; `ipinfo.io/ip` on the same inbound still returns the **Estonian** address
   (no blanket hijack).
3. On the box: `journalctl -u xray | grep 'accepted tcp:www.gosuslugi.ru'` — the flow really landed here.
4. `tail /var/log/scenario-fallback.log` after 2–3 timer cycles: `ru1:ok(...)` and an unchanged
   selector. A selector that keeps flipping means the probe is lying, not the node.

## Rollback

`scenario_override.json` → `{"bal-ru": ["p15","p16","p17","direct"]}` (or `["direct"]`),
`python3 scenario_routes.py install && vpn-cfg apply`. The `ru1` outbound can stay in the config
unused; delete it only in a separate pass, since removing it while a selector still names it trips
the lint.

## Optional: let one person dial the box directly (bypass the entry)

To test whether a Russian address alone unblocks a service, the owner needs a node whose first hop
is the box itself — the entry must be out of the path entirely. Second Reality inbound on its own
port (`8443`, clone of the 443 one, its own `shortId`), plus `ufw allow 8443/tcp`, is enough; no
nginx, no certificate, no DNS record. Reality answers a wrong client with the `dest` site
(`www.microsoft.com`), so an open port is a stealth surface, not an auth surface — still say it is
open and offer to allowlist his home IP. Ship it in **his token only** via `extra_nodes.json`
(`scenario-routes.md`), then prove it before he taps anything: a throwaway client to
`<ru-ip>:8443` must return the box address on `ipinfo`, `gosuslugi.ru` `200`. State the caveat
that this node is a Russian exit — blocked foreign services will *not* work through it.

## Pitfalls

- **`root` on Ubuntu has no password.** `ssh-copy-id root@<ip>` can never succeed, and the
  `Permission denied (publickey,password)` it prints looks like a wrong password. Add the key from
  the provider's VNC console (`sudo -i`, then append to `/root/.ssh/authorized_keys`, `chmod 700`
  the dir / `600` the file); Ubuntu's default `PermitRootLogin prohibit-password` then allows key
  login for root. Ansible-style `ssh <user>@` needs the account created at install time — try the
  distro defaults (`ubuntu`) only after reading `getent passwd` in the console.
- A VM that falls back to the installer's «Try or install Ubuntu» menu after a successful install
  is booting the **ISO**, not the disk: detach the image in the provider panel and put the disk
  first in the boot order. Keep the firmware mode the installer used — a `BIOS grub spacer` in the
  partition list means a legacy install, and booting it in UEFI mode finds no bootloader.
- A host without global IPv6 resolves AAAA records and then has nowhere to send them; keep
  `freedom.domainStrategy: "UseIPv4"` on such a box so clients are not left waiting on IPv6
  attempts. `ip -6 addr show scope global` and `ip -6 route get <aaaa>` answer this in one line.
- The RU box's own `freedom` means its exit IP **is** its public IP: verify with `curl ipify` on
  the box first, otherwise "the exit changed" is blamed on the entry.
- **Disabling SSH password auth silently does not stick on a cloud image.** `PasswordAuthentication no`
  in a fresh `/etc/ssh/sshd_config.d/99-*.conf` loses to `50-cloud-init.conf` saying `yes`, because sshd
  keeps the **first** value it reads, not the last. Change the cloud-init file too, add
  `ssh_pwauth: false` under `/etc/cloud/cloud.cfg.d/` so a reboot does not restore it, then prove it:
  `sshd -T | grep passwordauthentication` must say `no`, and a `PreferredAuthentications=password
  PubkeyAuthentication=no` attempt must answer `Permission denied (publickey)`. Confirm `authorized_keys`
  already holds your key **before** the reload — the console here is a browser tab, not a rescue mode.
- **Every selector change is a full `vpn-cfg apply`, i.e. a container restart.** Leaving flapping reseller
  relays beside `ru1` makes the watchdog re-apply roughly once a minute, and each apply restarts the entry.
  Once the owned box is in place keep the RU group at `[ru1, direct]` and drop the relays; a stable
  selector with one node is worth more than a pool that twitches.
- Do not sell the two-hop path as fast: client → Estonia → Moscow adds the measured ping to every
  request, and no config removes it. It is fine for gosuslugi, which is not a speed experience.

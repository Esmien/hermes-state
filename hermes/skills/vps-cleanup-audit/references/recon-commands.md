# Read-only recon batches for a foreign VPS

Run as root over SSH with the scratch wrapper (`sshpass` + `StrictHostKeyChecking=no`).
Group commands so a batch is one round-trip; keep every output bounded (`head`, `-xhd1`, `tail -n`).

## Batch 1 — identity and resources

```bash
hostname; . /etc/os-release; echo "$PRETTY_NAME"; uname -r; uptime
nproc; free -h | head -2; df -h /; who; last -n5 | head -5
```

Reads as: is this the right box, how much RAM/CPU/disk is there (decides whether an agent install is even viable), and **who else is logged in right now** (foreign root session = red flag to raise before deleting anything).

## Batch 2 — what actually runs

```bash
ss -tulpnH | awk '{print $1, $5, $7}' | sort -u | head -30
(docker ps -a --format '{{.Names}} | {{.Image}} | {{.Status}}' 2>/dev/null || echo "no docker cli")
systemctl --failed --no-legend --no-pager
systemctl list-unit-files --state=enabled --no-legend --no-pager \
  | grep -vE '^(systemd-|dbus|ssh|networking|networkd|resolved|rsyslog|cron|getty|multi-user|remote-fs|unattended|apparmor|e2scrub|man-db|apt-daily|dpkg|grub|snapd|cloud-init|open-vm|multipathd|udisks|packagekit|time-|local-fs|swap|sys-|proc-|dev-)'
```

`*:PORT` with a PID is the product; `127.0.0.1:PORT` is an internal/loopback backend.
The vendor regexp is the point: it collapses ~60 distro defaults so the few custom units stand out.
A `failed` row dated months ago is stale state, not an active problem.

## Batch 3 — footprint and leftovers

```bash
du -xhd1 / 2>/dev/null | sort -rh | head -12
du -xhd1 /var 2>/dev/null | sort -rh | head -6
ls -la /home /opt /srv
ls -la /root | head -25; ls -la /usr/local/bin /usr/local/sbin
awk -F: '$3>=1000 && $3<65534 {print $1, $3, $6, $7}' /etc/passwd
awk -F: '$3==0 {print $1}' /etc/passwd
crontab -l; ls -la /etc/cron.d/
snap list --all
ls -la /etc/systemd/system/ | grep -vE '^d|total'
```

`-xhd1` never crosses filesystems and never walks unbounded — mandatory on a 19 GB box as much as on a 4 TB one.
Empty `/opt` and `/srv`, one human user, one uid-0 account, and no non-symlink custom units = a clean application layer; say that out loud instead of padding the report.
Custom units appear as real files in `/etc/systemd/system`; symlinks there are distro aliases.

## Batch 4 — semantics: what is load-bearing

```bash
journalctl --disk-usage; du -xsh /var/log/* | sort -rh | head -8
ufw status; fail2ban-client status
du -xsh /usr/local/* /var/lib/* 2>/dev/null | sort -rh | head -8
ls -la /usr/local/<app>/bin 2>/dev/null
grep -o '"geoip:[a-zA-Z]*"\|"geosite:[a-zA-Z]*"' /usr/local/<app>/bin/config.json | sort -u
grep -h "^Start-Date\|^Commandline" /var/log/apt/history.log | tail -20
tail -30 /root/.bash_history
```

`bash_history` and `apt history` are the fastest way to see **how the box got dirty** (what was curl-bashed, what was installed by hand) — read them before guessing which dirs are abandoned.
Do not print tokens that may appear in history; paraphrase instead.

## App-specific checks

- **Postgres as a panel backend**: `sudo -u postgres psql -d <db> -c "\dt" | head -15` — table names tell you if it is the app's store.
- **Panel sqlite**: `/etc/<panel>/<panel>.db`; size plus `ls /etc/<panel>` is enough, never dump rows (secrets live there).
- **TLS**: `openssl x509 -enddate -noout -in /root/cert/<domain>/fullchain.pem` and `crontab -l | grep acme` — both must stay.
- **App binary size** vs its geo data: a single 77 MB Go binary plus 40–90 MB of `.dat` files is normal for xray, not bloat.

## Reporting

Convert every finding into `size + why-safe` (tier A) or `size + what decides it` (tier B).
Close with the concrete post-clean numbers the owner can hold you to: «было 7.0 ГБ занято → станет ~5.0 ГБ» (or ~3.1 ГБ with the agent removed).

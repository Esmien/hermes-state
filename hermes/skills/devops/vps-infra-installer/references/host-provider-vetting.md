# Vetting a host before paying (new VPS / RU node)

## Spec sanity for our workloads

- An Xray entry or relay (24 inbounds, blue/green pair) runs in ~120 MB RAM: **1 vCPU / 1–2 GB**
is plenty; paying for more buys nothing.
- Disk: **≥20 GB**. 10 GB survives only if nothing logs and no desktop is installed.
- **ISO = server/minimal, never `*-desktop`**: the desktop image pulls GNOME, eats ~8 GB of a
  10 GB disk and ~1.5 GB RAM for a UI nobody uses on a headless box.
- **Public dedicated IPv4 must be in the price** (not an extra line, not CGNAT). Without your own
  address the box is useless as an entry point.
- **Monthly billing first.** An unproven IP cannot be validated from the order form, only from
  inside the running server — a yearly prepay bets on something unmeasured.

## Registry checks (5 minutes, before paying)

```bash
whois <domain> | grep -Ei '^(domain|registrar|created|paid-till|nserver|org)'
dig +short <domain> A; dig +short <domain> NS
whois -h whois.cymru.com " -v <ip-from-A-record>"
```

What each answer buys:

- `created` / `paid-till` — an old domain paid years ahead is a different risk class from a
  month-old one.
- `nserver` on the provider's own domain means they run their own DNS, not a reseller panel.
- The Team Cymru line prints `AS | BGP prefix | CC | registry | allocated | AS name`. Their own
  AS **and** a prefix allocated years ago = the provider owns the network; a tiny prefix resold
  through someone else's AS = you are two hops from the real owner. `CC` confirms the address
  space is actually in the country you are buying.
- Read the offer/requisites pages through `read-untrusted` (a web page, not a command): legal
  entity, INN/OGRN, claimed own datacenter. A real ИНН/ОГРН and an old domain are the cheap
  filter against one-day resellers.

## Review quality

Positive reviews on hosting catalogs (sohost, glavhost, hostings.info, tophosts, hostinghub) and
on the provider's own site are marketing and say nothing. **The absence of complaints is not
proof of anything** — say it that way instead of certifying the provider. A public DDoS incident
in their own news is a real signal: they get hit, so do not expect premium uptime and keep a
second node elsewhere for the same role.

## Standing the box up after paying (Ubuntu Server, panel console)

Order-page choices that matter later: server ISO (never `*-desktop`), disk ≥20 GB, monthly
billing, and — for an RU node — check that the panel's boot mode and the way you install agree.

Installer screens, in the order they bite:

- **Storage:** subiquity leaves `/` at 10 GB and the rest free inside `ubuntu-vg`. Either set
  `ubuntu-lv` to the maximum on that screen, or accept 10 GB and grow later with
  `lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv && resize2fs /dev/ubuntu-vg/ubuntu-lv`.
  A ~1.7 GB `/boot` plus a 1 MB `BIOS grub spacer` means the install is **legacy BIOS** — keep the
  panel on BIOS, do not flip the VM to UEFI afterwards, or the disk will not boot.
- **Featured server snaps:** select nothing.
- **SSH setup:** tick `Install OpenSSH server`; skipping it costs a console-only recovery later.

After the first reboot the console showing «Try or install Ubuntu» is **the ISO booting**, not a
broken install: eject the ISO and put the disk first in the boot order. `no bootable device`
after that means the bootloader was never written — reinstall and wait for `Installation
complete` before `Reboot Now`.

`cloud-init … Used fallback datasource` / `DataSourceNone` followed by `cloud-final.service [ OK ]`
is normal for an ISO install and is not a hang — the login prompt scrolled off screen. Verify from
outside instead of reinstalling: port 22 answers, `nc <ip> 22 | head -1` prints
`SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13` (confirms 24.04 actually booted), and
`ssh -o BatchMode=yes -i <key> user@<ip> true` returns the offered auth methods.

**`root` has no password on Ubuntu, so `ssh-copy-id root@<ip>` can never work** — it is rejected
before the password is even compared. Get the key in from the VNC console: log in as the user the
installer created, `sudo -i`, then
`mkdir -p /root/.ssh && chmod 700 /root/.ssh`, append the public key to
`/root/.ssh/authorized_keys`, `chmod 600`. The default `PermitRootLogin prohibit-password` still
allows key login; only change it if `sshd_config` says `no`.

**A password prompt proves nothing about the username.** sshd answers identically for an account
that does not exist, so `Permission denied (publickey,password)` cannot distinguish a wrong
password from a mistyped login — stop retrying passwords and read the truth from the console
(`whoami`, `getent passwd`). Keep one dedicated key per role
(`ssh-keygen -t ed25519 -a 100 -f /root/.ssh/id_ed25519_<role>`) and hand the owner only the
`.pub`; it goes in the installer's «Import SSH key» field, which also lets password auth stay off.

## The caveat no provider will tell you

A datacenter address is refused by Госуслуги, banks and marketplaces **regardless of the country
the server stands in** — being in RU is necessary, not sufficient, for an RU-scenario exit. This
is provable only after the server is up: dial through it and request the actual target
(`http://www.gosuslugi.ru`, a bank, `wildberries.ru`), then decide whether to keep the plan.
State that up front when the owner is about to prepay for a year.

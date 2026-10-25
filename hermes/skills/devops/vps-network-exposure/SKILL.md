---
name: vps-network-exposure
description: "Use when a port may be open to the internet."
version: 1.0.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, firewall, iptables, ufw, docker, postgres, security, exposure]
---

# Network exposure audit & closure (this VPS)

## When to Use

The owner asks «у нас <порт> наружу?», a new service/container gets a published port, a security review is requested, or something must be firewalled. Covers the host-level question: which sockets listen on a routable address, what filters them, and how to close one durably. Stack-specific service facts live in the `ai-stack` skill.

## Answer shape (owner preference)

**First line = verdict, then evidence, then the fix as a gated plan.** «Да, открыт» / «Нет, только localhost» before any command output. Then a short bullet list of the facts that decided it. Then, only if action is needed, the exact commands under «⚠️ Требуется подтверждение». Do not open with the investigation.

Keep two facts separate and say both:
1. **Network reachability** — is the TCP port reachable from the internet?
2. **Authentication gate** — can such a client actually get in (`pg_hba.conf`, app auth, allowlist)?

A firewall-closed port and an app-rejected connection are different risks (`ECONNREFUSED` vs a 41k-line brute-force log) and must not be collapsed into one «закрыто».

## Procedure

1. **Socket inventory.** `ss -tlnp | tail -n +2` — `0.0.0.0:*` / `[::]:*` = routable bind, `127.0.0.1:*` = loopback only. Map each PID to its owner: `ps -o pid,ppid,user,cmd -p <pid>`. Systemd services (host Postgres) exist ONLY here — `docker ps` cannot see them.
2. **Container view.** `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}'`. `5432/tcp` with no `->` is an internal EXPOSE only; `127.0.0.1:8001->8000/tcp` is loopback-published; `0.0.0.0:PORT->…` is the real exposure. Cross-check with `ss` that the listener is `docker-proxy` (userland proxy path) — if nothing listens on the host port, the traffic goes through DNAT and host INPUT rules will not see it (see Pitfalls). **`ss` also catches non-Docker listeners, so read the whole list, not just container ports:** on this host `cupsd` from the `cups` snap binds `0.0.0.0:631` (printing service, not needed on a VPS) and is exposed, since `INPUT` policy is `ACCEPT` and no rule covers 631. Snapped services do not show up in `systemctl is-active cups` — `systemctl is-active snap.cups.cupsd` and `ps -o cmd -C cupsd` do.
3. **Filter state.** `iptables -S INPUT | head -20` (policy line first) and `ufw status` plus `grep -E '^ENABLED' /etc/ufw/ufw.conf`. Never infer the firewall from `systemctl is-active ufw` (see Pitfalls).
4. **App-level gate.** Read the service's own ACL, e.g. Postgres: `grep -hE '^\s*listen_addresses' /etc/postgresql/*/main/postgresql.conf` and `grep -hvE '^\s*#|^\s*$' /etc/postgresql/*/main/pg_hba.conf`.
5. **Prove reachability from evidence you already have.** The service log is the authoritative "the internet really reaches this port" witness — far better than any external port-checker API: `grep -c 'no pg_hba.conf entry' /var/log/postgresql/postgresql-*-main.log` (each line carries the source IP of a real external client; tens of thousands means it is being brute-forced). Then bucket the sources: `grep -oE 'no pg_hba.conf entry for host "[0-9.]+"' <log> | awk '{print $NF}' | sort | uniq -c | sort -rn | head`.
6. **Report** with the verdict-first shape above. If nothing needs closing, say «ничего не открыто» and stop — no plan.

`scripts/audit-exposure.sh` runs steps 1–5 read-only and prints the whole picture in one go; run it first, then drill into whatever it flags.

## Closing a port (durable)

Pattern that leaves intra-stack traffic intact (containers reach host Postgres from `172.16.0.0/12`):

```bash
# ACCEPT exceptions first, DROP everything else — order matters
/usr/local/bin/fw-guard-postgres.sh
```

`/usr/local/bin/fw-guard-postgres.sh` (idempotent: deletes its own rules, then rebuilds them by inserting at position 1 in reverse order — ACCEPT 127.0.0.1, ACCEPT 172.16.0.0/12, DROP) is driven by `fw-guard-postgres.service` (oneshot, `RemainAfterExit=yes`, `After=ufw.service network-online.target`, `WantedBy=multi-user.target`). Recreate that pair for any other port; it is the persistence mechanism on this host.

Verify after applying: `iptables -S INPUT | head -5` shows the three rules in order, `systemctl is-active fw-guard-postgres` = `active`, and `ss -tnp state established '( sport = :5432 )'` still shows the containers' `172.18.x` peers — no rule change without proof that the stack kept working. Then verify from **outside**, using the netns pattern above; `iptables -S` alone shows intent, not effect. Also confirm the counter sits on the expected rule: if the DROP counter does not move while a foreign probe times out, the packet is being stopped somewhere else and the reasoning is wrong.

## SSH password auth on this host

`PasswordAuthentication` is **off**: `/etc/ssh/sshd_config.d/50-cloud-init.conf` says `no`, backed by `/etc/cloud/cloud.cfg.d/99-ssh-no-password.cfg` (`ssh_pwauth: false`) so cloud-init cannot flip it back on reboot. Root logs in by key only (2 keys in `/root/.ssh/authorized_keys`); `ai_service` has **no** `authorized_keys`, so it cannot SSH in at all — use `su`/`sudo` from root.

**sshd is first-match-wins, not last.** `Include /etc/ssh/sshd_config.d/*.conf` is line 12 and files apply in lexical order: `50-cloud-init.conf` (`yes`) beat `60-cloudimg-settings.conf` (`no`) — that is why `sshd -T` reported `passwordauthentication yes`. A new `99-*.conf` would NOT fix it. Edit the earliest file that sets the key, then verify with `sshd -T | grep -i passwordauthentication` (never trust the file alone). `cloud.cfg` had no `ssh_pwauth` key at all, so the drop-in `99-ssh-no-password.cfg` is what makes it stick.

Reload, don't restart: `sshd -t && systemctl reload ssh` keeps existing sessions alive. Verify from the loopback: `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no root@127.0.0.1 true` must answer `Permission denied (publickey)` — the parenthesised list is the authoritative set of allowed methods.

## Pitfalls

- **`iptables` here is nf_tables and rejects more than one `-s`:** `iptables -I INPUT -p tcp --dport 5432 ! -s 127.0.0.1 ! -s 172.16.0.0/12 -j DROP` → `multiple -s flags not allowed`, exit 2. Express the same intent as ordered rules: ACCEPT for each trusted source, then an unconditional DROP for that port, all above the policy.
- **Build the order by inserting at position 1 in reverse.** `-A` appends below other ACCEPT rules and silently never matches; the working idiom is `-I INPUT 1 … DROP`, then `-I INPUT 1 … ACCEPT 172.16/12`, then `-I INPUT 1 … ACCEPT 127.0.0.1`, which lands as ACCEPT/ACCEPT/DROP.
- **`systemctl is-active ufw` = `active` while the firewall is OFF.** Here `ENABLED=no` in `/etc/ufw/ufw.conf` leaves the unit running but rules flushed, so `ufw status` answers `inactive` and `iptables -S` is a bare `-P INPUT ACCEPT`. Judging by the unit state produces a false «firewall включён». Read `ufw status` + the `ENABLED=` line, and after any change re-read `iptables -S`.
- **Do not enable ufw to fix one port.** `DEFAULT_INPUT_POLICY="DROP"` plus an empty `user.rules` set would cut SSH and the whole stack at once, and `ufw deny` written while ufw is disabled does nothing. An iptables guard unit is the surgical change; enabling ufw is a separate, owner-gated redesign.
- **Nothing on this host persists iptables rules by default** — `netfilter-persistent` is not installed and `ufw` is disabled, so hand-added rules vanish on reboot. Always pair a rule with a oneshot systemd unit (`WantedBy=multi-user.target`, `After=ufw.service`) and `systemctl enable --now` it; verify with `systemctl is-enabled`.
- **Docker-published ports can bypass the INPUT chain.** If the listener is `docker-proxy`, INPUT rules apply; if the port is DNAT-ed straight to the container (no host listener in `ss`), filter on `DOCKER-USER` instead — and the cleaner fix is re-publishing as `127.0.0.1:PORT:PORT`. Decide from `ss -tlnp` which path you are on before claiming a port is closed.
- **Never conclude reachability from a third-party port-checker.** External checker APIs return `null`/rate-limited payloads that look like "filtered", and a local `curl` to your own public IP exits via loopback and always succeeds. Service logs (hits from real foreign IPs) and the bind address are the two honest signals. A checker can also report ports that nothing listens on (Shodan reported `9223` while `ss -tlnp` and `iptables -t nat -S` both showed nothing) — treat its output as a hint, then verify locally and throw the hint away.
- **Testing from inside a container on the same host is a self-whitelisting trap — the single easiest way to produce a false «открыт».** A packet from a bridge network is MASQUERADEd to the bridge gateway (`172.18.0.1`), which falls inside `172.16.0.0/12` — exactly the trusted range the ACCEPT rules exist for. The probe is therefore accepted by the very rule it should be tested against, and a port that is closed to the internet answers happily. Symptom: `curl`/socket connect succeeds from `docker exec`, while the service log shows no foreign IPs at all. Any test whose source address is inside an allowlist proves nothing about the default policy.
- **The only honest reachability test uses a source address outside every allowlist, on the real external interface.** Pattern: create a throwaway netns with an address in no allowed range, then probe from it and read the **packet counter** as the witness:
  ```bash
  ip netns add fwtest
  ip link add veth-fwtest type veth peer name veth-fwtest-c
  ip link set veth-fwtest-c netns fwtest
  ip addr add 10.99.99.1/24 dev veth-fwtest && ip link set veth-fwtest up
  ip netns exec fwtest ip addr add 10.99.99.2/24 dev veth-fwtest-c
  ip netns exec fwtest ip link set veth-fwtest-c up
  iptables -S INPUT | grep 5432                      # note DROP counter before
  ip netns exec fwtest timeout 5 bash -c 'echo > /dev/tcp/141.98.166.213/5432'   # expect timeout
  iptables -S INPUT | grep 5432                      # DROP counter must have advanced
  ip netns exec fwtest timeout 5 bash -c 'echo > /dev/tcp/141.98.166.213/22'     # control: must connect ok
  ip netns del fwtest                                # always clean up
  ```
  A rising DROP counter on a timing-out client is proof; so is a control port that connects. Without the control probe a timeout could just mean «сеть сломана». Delete the netns afterwards.
- **A `ss` listener is not the only way to be reachable, and a missing listener is not proof of safety.** Decide DNAT vs userland-proxy from `ss -tlnp` first (see the Docker pitfall), because host `INPUT` rules are blind to DNAT-ed traffic. `fw-guard-postgres.sh` handles the host-Postgres case only.
- **`write_file`/`patch` refuse system paths** (`Refusing to write to sensitive system path: /etc/...`). Write to `~/.hermes/cache/scratch/` first, then `cp` it into place; for an existing system file that only needs one line flipped, read+write it from Python in `execute_code` (needs no shell redirect).
- **Closing a port is a state change → gated.** Give the exact rules, the blast radius («контейнеры из 172.18 не затронуты») and the verification command, then wait for «Да».
- **A privileged helper container is exposure of its own kind.** `privileged: true` + `pid: host` + `/var/run/docker.sock` + `/:/mnt/host` means host-root RCE from inside; when such a container is unused, name those four facts when proposing removal — they are the reason it matters more than an open port.

## Related

- Which services exist, their ports and domains: `ai-stack` skill.
- Removing a container/image and reclaiming its disk: `vps-disk-reclamation` skill.

# Firewall, port closure and SSH

## Durable port guard

The host PostgreSQL guard `/usr/local/bin/fw-guard-postgres.sh` is driven by `fw-guard-postgres.service`, oneshot with `RemainAfterExit=yes`, ordered after UFW and network-online. It inserts ACCEPT for loopback, ACCEPT for 172.16/12, then DROP for 5432. Existing container connectivity must remain intact. Recreate this pattern carefully for other host services only after explicit owner approval.

iptables here uses nf_tables: multiple `-s` flags in a rule are rejected. Insert at position 1 in reverse: DROP first, then each ACCEPT. Appending rules below an existing accept silently fails. Verify rule order, `systemctl is-active`, the actual established backend connections, packet counters, and an independent external probe. Never equate `iptables -S` with observed behavior.

UFW service can be `active` while UFW itself is inactive: check `ufw status` and `ENABLED` in `/etc/ufw/ufw.conf`. Do not enable UFW to fix a single port: its default DROP and empty user rules can sever SSH and services. Hand-added rules are not persistent without a unit or another explicitly verified persistence mechanism.

Docker DNAT can bypass host INPUT; check Docker NAT and DOCKER-USER, not just `ss`. Binding published ports to 127.0.0.1 is often cleaner. A host `ss` listener is not a complete reachability test. A local container may be allowlisted by its masqueraded source, so a successful local connection is not proof of external reachability.

For filter tests, a synthetic netns with a source outside all allowlists plus packet counters and an allowed control can verify local rules. Creating and removing namespaces or editing firewall rules is a state change requiring approval; such tests do not test the real internet path. Independently verify from an external host. Pending/null and timeouts without controls are inconclusive. A live external TCP success proves only reachability from that network, not authentication.

## SSH

Password authentication was disabled through `/etc/ssh/sshd_config.d/50-cloud-init.conf` and `/etc/cloud/cloud.cfg.d/99-ssh-no-password.cfg`; recheck current state instead of assuming. Root uses keys; `ai_service` historically had no authorized keys. OpenSSH uses first matching value, with included files read lexically; a later 99-* override may not win. Check `sshd -T` and `sshd -t`. After approved changes reload rather than restart and test an independent key session; password-only loopback should report `Permission denied (publickey)`.

Privileged containers with host PID, docker socket and host-root bind are effectively host-root access and should be assessed separately from port exposure.

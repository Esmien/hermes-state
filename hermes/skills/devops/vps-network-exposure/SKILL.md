---
name: vps-network-exposure
description: "Use when a port may be open to the internet."
version: 1.1.0
author: VPS Admin
license: MIT
metadata:
  hermes:
    tags: [devops, firewall, iptables, ufw, docker, postgres, security, exposure]
---

# Network exposure on this VPS

Use for public ports, host or Docker listeners, firewall and access-control audits, VPN ingress and safe port closure.

## Core procedure

1. Inventory host listeners with `ss -tlnp` and Docker publications with `docker ps`; inspect both because host services are not in Docker, and published ports can use DNAT. `0.0.0.0`/`[::]` can be routable; loopback is local only. Verify actual filtering and bind address rather than relying on container EXPOSE.
2. Check `ufw status`, current iptables/nftables rules and service ACLs. An active UFW systemd unit does not mean the firewall is enabled. Do not enable UFW as a one-port fix; it may cut SSH and services.
3. Run `bash scripts/audit-exposure.sh` from this skill directory for local inventory, then drill into findings. It does not test external reachability.
4. Probe from an independent external network where appropriate; check current service evidence and counters. Local or same-host-container probes can be allowlisted. A successful external TCP test proves reachability from that source only, not app authentication or reachability from the owner's ISP; pending/null or a timeout alone is inconclusive.
5. Report the verdict first, then concise evidence. Distinguish network reachability from app-level authorization. For changes give exact commands, impact and rollback, and obtain explicit approval; verify live access and persistence afterward. Do not expose secrets or unbounded logs.

## Load relevant reference before changes

- [Firewall, Docker filtering, persistent guard and SSH](references/firewall-and-ssh.md): rule ordering, UFW pitfalls, SSH and verification.
- [fail2ban and Nginx rate limiting](references/fail2ban-and-rate-limits.md): current configuration and safety checks.
- [VPN and shared HTTPS ingress](references/vpn-and-https-ingress.md): 3x-ui, tunnel diagnosis, port 443, client-IP preservation and recovery.

For stack services use `ai-stack`; for removing containers or reclaiming space use `vps-disk-reclamation`.

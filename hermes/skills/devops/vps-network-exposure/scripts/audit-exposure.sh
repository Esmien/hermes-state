#!/bin/bash
# Read-only exposure inventory for this VPS. Changes nothing.
set -u

section() { printf '\n===== %s =====\n' "$1"; }

section "listeners (routable first)"
ss -tlnp 2>/dev/null | tail -n +2 | awk '{print $4"  "$NF}' | sort

section "docker published ports"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' 2>/dev/null | grep -- '->' || echo '(no published ports)'

section "firewall"
printf 'iptables INPUT policy/first rules:\n'
iptables -S INPUT 2>/dev/null | head -15
printf 'ufw status: '
ufw status 2>/dev/null | head -1
grep -HE '^ENABLED' /etc/ufw/ufw.conf /etc/default/ufw 2>/dev/null
printf 'netfilter-persistent: '
command -v netfilter-persistent >/dev/null 2>&1 && echo present || echo ABSENT
printf 'guard units: '
systemctl list-unit-files 'fw-guard-*' --no-legend 2>/dev/null | awk '{print $1"("$2")"}' | tr '\n' ' '; echo

section "postgres (host)"
grep -hE '^[[:space:]]*listen_addresses' /etc/postgresql/*/main/postgresql.conf 2>/dev/null
grep -hvE '^[[:space:]]*#|^[[:space:]]*$' /etc/postgresql/*/main/pg_hba.conf 2>/dev/null | head -20
printf 'external hba rejects in log: '
grep -c 'no pg_hba.conf entry' /var/log/postgresql/postgresql-*-main.log 2>/dev/null | tail -1
printf 'top source IPs:\n'
grep -ohE 'no pg_hba.conf entry for host "[0-9.]+"' /var/log/postgresql/postgresql-*-main.log 2>/dev/null \
  | grep -oE '[0-9.]+' | sort | uniq -c | sort -rn | head -5

section "what a listener actually is"
printf 'resolve a PID with: ps -o pid,ppid,user,cmd -p <PID>\n'

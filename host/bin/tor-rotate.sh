#!/bin/bash
# Rotate Tor circuit (SIGNAL NEWNYM) via control port.
# Used by cron to periodically switch exit nodes, reducing search-engine bans.
set -u

PW_FILE=/etc/tor/control-password
CTRL=127.0.0.1:9051

if [ ! -r "$PW_FILE" ]; then
  echo "tor-rotate: control password file $PW_FILE not readable" >&2
  exit 1
fi

PW=$(cat "$PW_FILE")

# Open a TCP connection to the control port using bash's /dev/tcp
exec 3<>"/dev/tcp/${CTRL%:*}/${CTRL##*:}" || { echo "tor-rotate: cannot connect to $CTRL" >&2; exit 1; }

# Authenticate
printf 'AUTHENTICATE "%s"\r\n' "$PW" >&3
IFS= read -r resp <&3
case "$resp" in
  250*) ;;
  *) echo "tor-rotate: AUTH failed: $resp" >&2; exec 3>&-; exit 1 ;;
esac

# Request a new circuit
printf 'SIGNAL NEWNYM\r\n' >&3
IFS= read -r resp <&3
case "$resp" in
  250*) ;;
  *) echo "tor-rotate: NEWNYM failed: $resp" >&2; exec 3>&-; exit 1 ;;
esac

exec 3>&-
echo "tor-rotate: circuit rotated at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit 0
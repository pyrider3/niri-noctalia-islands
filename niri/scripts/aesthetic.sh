#!/usr/bin/env bash
# Usage: aesthetic.sh on|off|restore [backup-dir]
set -e
D="$HOME/.config/niri"; C="$D/config.kdl"; L='include optional=true "aesthetic.kdl"'
case "$1" in
  off)  grep -vxF "$L" "$C" > "$C.tmp" && mv "$C.tmp" "$C" ;;
  on)   grep -qxF "$L" "$C" || printf '\n%s\n' "$L" >> "$C" ;;
  restore) cp "${2:-$(ls -d $D/aesthetic-backups/* | head -1)}/config.kdl" "$C" ;;
  *) echo "usage: $0 on|off|restore [dir]"; exit 1 ;;
esac
niri validate -c "$C" && echo "ok: $1"

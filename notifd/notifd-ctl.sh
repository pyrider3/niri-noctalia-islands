#!/usr/bin/env bash
# notifd-ctl.sh  status | on | off | restart
#   on      Noctalia stops serving notifications, notifd takes over (and starts at login)
#   off     notifd stops, Noctalia serves notifications again, bar goes back to the built-in bell
set -u
N="$HOME/.config/notifd"
NIRI_INC="$HOME/.config/niri/notifd.kdl"
NIRI_CFG="$HOME/.config/niri/config.kdl"
INC_LINE='include optional=true "notifd.kdl"'
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

owner() { busctl --user status org.freedesktop.Notifications 2>/dev/null | awk -F= '/^Comm=/{print $2}'; }
running() { pgrep -f "^/usr/bin/python3 .*notifd.py" >/dev/null || pgrep -f "^python3 .*notifd/notifd.py" >/dev/null; }
stop_daemon() { pkill -f "notifd/notifd.py" 2>/dev/null; pkill -f "^/usr/bin/python3 /home/.*/notifd.py" 2>/dev/null; sleep 0.8; }

start_daemon() {
  nohup setsid python3 "$N/notifd.py" >> "$HOME/.local/state/notifd/run.log" 2>&1 < /dev/null &
}


bar() {  # bar on|off : swap Noctalia's built-in bell for the notifd bell in the bar
  python3 - "$1" <<'PY'
import re, sys
mode = sys.argv[1]
p = __import__('os').path.expanduser('~/.local/state/noctalia/settings.toml')
s = open(p).read()
if mode == 'on':
    s = re.sub(r'^(end = \[.*?)"notifications"(.*\])$', r'\1"notifd-bell"\2', s, count=1, flags=re.M)
    if '[widget.notifd-bell]' not in s:
        s = s.replace('[widget.network]', '[widget.notifd-bell]\ntype = "local/notifd-bell:bell"\n\n[widget.network]', 1)
    if '"local/notifd-bell"' not in s:
        s = s.replace('"local/status-capsule"\n]', '"local/status-capsule",\n    "local/notifd-bell"\n]', 1)
else:
    s = re.sub(r'^(end = \[.*?)"notifd-bell"(.*\])$', r'\1"notifications"\2', s, count=1, flags=re.M)
open(p, 'w').write(s)
PY
  noctalia msg config-reload >/dev/null
  sleep 1.5      # let Noctalia finish re-reading before anything else makes it save its settings
}

case "${1:-status}" in
  status)
    echo "notification owner: $(owner || echo none)"
    echo "noctalia enable_daemon: $(noctalia msg config-get notification.enable_daemon 2>&1)"
    ;;
  on)
    noctalia msg config-set notification.enable_daemon false >/dev/null
    for i in 1 2 3 4 5 6; do [ -z "$(owner)" ] && break; sleep 0.5; done
    stop_daemon
    start_daemon
    for i in 1 2 3 4 5 6 7 8; do [ "$(owner)" = "python3" ] && break; sleep 0.5; done
    if [ "$(owner)" != "python3" ]; then
      echo "notifd did not take over (owner: $(owner || echo none)); reverting" >&2
      stop_daemon; noctalia msg config-set notification.enable_daemon true >/dev/null; exit 1
    fi
    printf '// Managed by ~/.config/notifd/notifd-ctl.sh\nspawn-at-startup "python3" "%s/notifd.py"\n' "$N" > "$NIRI_INC"
    grep -qxF "$INC_LINE" "$NIRI_CFG" || printf '\n%s\n' "$INC_LINE" >> "$NIRI_CFG"
    bar on
    echo "on: notifd is serving notifications"
    ;;
  off)
    bar off
    stop_daemon
    noctalia msg config-set notification.enable_daemon true >/dev/null
    rm -f "$NIRI_INC"
    grep -vxF "$INC_LINE" "$NIRI_CFG" > "$NIRI_CFG.tmp" && mv "$NIRI_CFG.tmp" "$NIRI_CFG"
    echo "off: Noctalia serves notifications again (owner: $(owner || echo none))"
    ;;
  bar) bar "${2:-on}"; echo "bar: $2" ;;
  style)  # Noctalia's setting is the source of truth, so change it there and tell the daemon right away
    st="${2:-card}"
    python3 - "$st" <<'PY'
import os, re, sys
st = sys.argv[1]
p = os.path.expanduser('~/.local/state/noctalia/settings.toml')
s = open(p).read()
sec = '[plugin_settings."local/notifd-bell"]'
if sec in s:
    s = re.sub(r'(\[plugin_settings\."local/notifd-bell"\]\n)(style = ".*?"\n)?', r'\1style = "%s"\n' % st, s, count=1)
else:
    s = s.replace('[plugin_settings."pyrider3/media-capsule"]', sec + '\nstyle = "%s"\n\n[plugin_settings."pyrider3/media-capsule"]' % st, 1)
open(p, 'w').write(s)
PY
    busctl --user call dev.pr.Notifd /dev/pr/Notifd dev.pr.Notifd SetStyle s "$st" >/dev/null
    noctalia msg config-reload >/dev/null
    sleep 1.5
    echo "style: $st" ;;
  restart)
    stop_daemon; start_daemon; sleep 1.5; echo "owner: $(owner || echo none)"
    ;;
  *) echo "usage: $0 status|on|off|restart|bar on|bar off|style card|frost|island|capsule|bell"; exit 1 ;;
esac

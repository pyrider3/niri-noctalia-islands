#!/bin/bash
# clock-ctl.sh on|off : swap Noctalia's built-in bar clock for the animated clock-island widget (and back)
set -e
python3 - "$1" <<'PY'
import os, re, sys
mode = sys.argv[1]
p = os.path.expanduser('~/.local/state/noctalia/settings.toml')
s = open(p).read()
if mode == 'on':
    s = re.sub(r'^(start = \[ )"clock"', r'\1"clock-island"', s, count=1, flags=re.M)
    if '[widget.clock-island]' not in s:
        s = s.replace('[widget.network]', '[widget.clock-island]\ntype = "local/clock-island:clock"\n\n[widget.network]', 1)
    if '"local/clock-island"' not in s:
        s = s.replace('"local/notifd-bell"\n]', '"local/notifd-bell",\n    "local/clock-island"\n]', 1)
else:
    s = re.sub(r'^(start = \[ )"clock-island"', r'\1"clock"', s, count=1, flags=re.M)
open(p, 'w').write(s)
PY
noctalia msg config-reload >/dev/null
sleep 1.5

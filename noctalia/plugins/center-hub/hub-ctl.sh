#!/bin/bash
# hub-ctl.sh on|off : add / remove the center hub next to the original cyber-ruler in the bar's centre
set -e
python3 - "$1" <<'PY'
import os, re, sys
mode = sys.argv[1]
p = os.path.expanduser('~/.local/state/noctalia/settings.toml')
s = open(p).read()
if mode == 'on':
    if '"center-hub"' not in s.split('[bar.default]')[1].split('\n')[4]:
        s = re.sub(r'^(center = \[ )', r'\1"center-hub", ', s, count=1, flags=re.M)
    if '[widget.center-hub]' not in s:
        s = s.replace('[widget.network]', '[widget.center-hub]\ntype = "local/center-hub:hub"\n\n[widget.network]', 1)
    if '"local/center-hub"' not in s:
        s = s.replace('"local/clock-island"\n]', '"local/clock-island",\n    "local/center-hub"\n]', 1)
else:
    s = s.replace('"center-hub", ', '', 1)
open(p, 'w').write(s)
PY
noctalia msg config-reload >/dev/null
sleep 1.5

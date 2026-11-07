#!/bin/bash
# tray-ctl.sh on|off : swap Noctalia's built-in tray for the tray island in the bar (and back)
set -e
python3 - "$1" <<'PY'
import os, re, shutil, sys, time
mode = sys.argv[1]
p = os.path.expanduser('~/.local/state/noctalia/settings.toml')
shutil.copy(p, os.path.expanduser('~/.config/noctalia/plugin-backups/settings.before-tray-%s-%d.toml' % (mode, int(time.time()))))
s = open(p).read()
if mode == 'on':
    s = re.sub(r'(^end = \[\s*)"tray"', r'\1"tray-island"', s, count=1, flags=re.M)
    if '[widget.tray-island]' not in s:
        s = s.replace('[widget.tray]', '[widget.tray-island]\ntype = "local/tray-island:tray"\n\n[widget.tray]', 1)
    if '"local/tray-island"' not in s:
        s = re.sub(r'(^enabled = \[)', r'\1\n    "local/tray-island",', s, count=1, flags=re.M)
else:
    s = re.sub(r'(^end = \[\s*)"tray-island"', r'\1"tray"', s, count=1, flags=re.M)
open(p, 'w').write(s)
PY
noctalia msg config-reload >/dev/null
sleep 1.5

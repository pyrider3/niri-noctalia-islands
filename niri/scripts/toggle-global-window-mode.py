#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CONFIG = Path.home() / '.config/niri'
RULE = CONFIG / 'global-window-mode.kdl'


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=10).stdout


def main():
    lock_path = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'niri-global-mode-{os.getuid()}.lock'
    with lock_path.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = RULE.read_text()
        floating = 'open-floating true' in previous
        if '--restore' not in sys.argv:
            floating = not floating
        mode = 'true' if floating else 'false'
        xray = 'false' if floating else 'true'
        temporary = RULE.with_suffix('.kdl.tmp')
        temporary.write_text('// Managed by scripts/toggle-global-window-mode.py.\n'
                             f'window-rule {{\n    open-floating {mode}\n'
                             f'    background-effect {{ xray {xray}; }}\n}}\n')
        temporary.replace(RULE)
        try:
            run('niri', 'validate', '--config', str(CONFIG / 'config.kdl'))
            run('niri', 'msg', 'action', 'load-config-file')
        except Exception:
            RULE.write_text(previous)
            raise
        action = 'move-window-to-floating' if floating else 'move-window-to-tiling'
        # A second snapshot covers windows opened while the config was reloading.
        for _ in range(2):
            for window in json.loads(run('niri', 'msg', '-j', 'windows')):
                if window['is_floating'] != floating:
                    try:
                        run('niri', 'msg', 'action', action, '--id', str(window['id']))
                    except subprocess.CalledProcessError:
                        remaining = json.loads(run('niri', 'msg', '-j', 'windows'))
                        if any(w['id'] == window['id'] for w in remaining):
                            raise
            time.sleep(0.1)
        if floating and subprocess.run(['pgrep', '-u', str(os.getuid()), '-x', 'noctalia'],
                                       stdout=subprocess.DEVNULL).returncode:
            subprocess.Popen(['noctalia', '-d'], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for attempt in range(30):
            try:
                run('noctalia', 'msg', 'dock-show' if floating else 'dock-hide')
                break
            except subprocess.CalledProcessError:
                if not floating or attempt == 29:
                    raise
                time.sleep(0.2)
        print('floating' if floating else 'tiling')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Global window mode: {error}', file=sys.stderr)
        sys.exit(1)

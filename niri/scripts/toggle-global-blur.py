#!/usr/bin/env python3
import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import sys

CONFIG = Path.home() / '.config/niri'
FOCUSED = '--focused' in sys.argv
RULE = CONFIG / ('focused-blur.kdl' if FOCUSED else 'global-blur.kdl')


def run(*args):
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=10)


def write_rule(text):
    temporary = RULE.with_suffix('.kdl.tmp')
    temporary.write_text(text)
    temporary.replace(RULE)


def main():
    # Share the mode-switch lock so concurrent config reloads remain ordered.
    lock_path = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'niri-global-mode-{os.getuid()}.lock'
    with lock_path.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = RULE.read_text()
        if FOCUSED:
            window = json.loads(subprocess.check_output(
                ['niri', 'msg', '-j', 'focused-window'], text=True, timeout=10))
            if window is None or not window.get('app_id'):
                return
            app = window['app_id']
            marker = '// app-blur-state: '
            states = {}
            for line in previous.splitlines():
                if line.startswith(marker):
                    states = json.loads(line[len(marker):])
            default = app != 'kitty'
            enabled = not states.get(app, default)
            states[app] = enabled
            text = ('// Managed by scripts/toggle-global-blur.py --focused.\n'
                    + marker + json.dumps(states, ensure_ascii=True) + '\n')
            for app_id, blur in sorted(states.items()):
                pattern = '^' + re.sub(r'([\\.^$|?*+()\[\]{}])', r'\\\1', app_id) + '$'
                text += ('window-rule {\n    match app-id=' + json.dumps(pattern)
                         + '\n    background-effect { blur '
                         + ('true' if blur else 'false') + '; }\n}\n')
        else:
            enabled = '    off' in previous
            text = ('// Managed by scripts/toggle-global-blur.py.\n'
                    + ('blur {}\n' if enabled else 'blur {\n    off\n}\n'))
        write_rule(text)
        try:
            run('niri', 'validate', '--config', str(CONFIG / 'config.kdl'))
            run('niri', 'msg', 'action', 'load-config-file')
        except Exception:
            write_rule(previous)
            run('niri', 'msg', 'action', 'load-config-file')
            raise
        target = app if FOCUSED else 'global'
        print(f'{target}: blur enabled' if enabled else f'{target}: blur disabled')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Global blur: {error}', file=sys.stderr)
        sys.exit(1)

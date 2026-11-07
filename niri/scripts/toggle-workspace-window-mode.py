#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys


def query(name):
    result = subprocess.run(['niri', 'msg', '-j', name], check=True,
                            capture_output=True, text=True, timeout=10)
    return json.loads(result.stdout)


def main():
    lock_path = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'niri-global-mode-{os.getuid()}.lock'
    with lock_path.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        workspace = next((w for w in query('workspaces') if w['is_focused']), None)
        if workspace is None:
            return
        windows = [w for w in query('windows') if w['workspace_id'] == workspace['id']]
        if not windows:
            return
        # Mixed layouts become uniformly floating; a fully floating workspace tiles.
        floating = not all(w['is_floating'] for w in windows)
        action = 'move-window-to-floating' if floating else 'move-window-to-tiling'
        if '--dry-run' in sys.argv:
            print(json.dumps({'workspace_id': workspace['id'], 'floating': floating,
                              'window_ids': [w['id'] for w in windows]}))
            return
        for window in windows:
            if window['is_floating'] == floating:
                continue
            try:
                subprocess.run(['niri', 'msg', 'action', action, '--id', str(window['id'])],
                               check=True, capture_output=True, text=True, timeout=10)
            except subprocess.CalledProcessError:
                if any(w['id'] == window['id'] for w in query('windows')):
                    raise
        print('workspace floating' if floating else 'workspace tiling')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Workspace window mode: {error}', file=sys.stderr)
        sys.exit(1)

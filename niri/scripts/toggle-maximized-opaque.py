#!/usr/bin/python3
"""Toggle work-area maximize and compositor opacity on the same niri window."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def request(*args):
    result = subprocess.run(['niri', 'msg', *args], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'niri IPC failed')
    return result.stdout


def toggle():
    window = json.loads(request('--json', 'focused-window'))
    if window is None: return
    identifier = str(window['id'])
    # Capture the ID once: both actions still target this window if focus changes.
    request('action', 'toggle-window-rule-opacity', '--id', identifier)
    try:
        request('action', 'maximize-window-to-edges', '--id', identifier)
    except Exception:
        # Do not leave opacity changed if maximizing failed.
        request('action', 'toggle-window-rule-opacity', '--id', identifier)
        raise


def main():
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime: raise RuntimeError('XDG_RUNTIME_DIR is not set; run inside your niri session')
    session = hashlib.sha256(os.environ.get('NIRI_SOCKET', '').encode()).hexdigest()[:12]
    with (Path(runtime) / ('niri-maximized-opaque-' + session + '.lock')).open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        toggle()

if __name__ == '__main__':
    try: main()
    except Exception as error:
        print('niri maximize/opacity:', error, file=sys.stderr)
        sys.exit(1)

"""Small shared helpers (state directory, json read/save, colours)."""
import json
import os
from pathlib import Path

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'notion-now'


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(path, value):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False)
    tmp.replace(path)


def rgba(hex_value, alpha=1):
    return tuple(int(hex_value[i:i + 2], 16) / 255 for i in (1, 3, 5)) + (alpha,)

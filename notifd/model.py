"""Notification data model + persistent history."""
import json
import os
import time
from pathlib import Path

STATE_DIR = Path.home() / '.local/state/notifd'
HISTORY = STATE_DIR / 'history.json'
STATE_FILE = STATE_DIR / 'state.json'

LOW, NORMAL, CRITICAL = 0, 1, 2


class Notif:
    __slots__ = ('id', 'app', 'summary', 'body', 'icon', 'image', 'actions', 'urgency',
                 'timeout', 'ts', 'category', 'resident', 'transient', 'desktop')

    def __init__(self, id, app, summary, body, icon, actions, urgency, timeout, category='',
                 resident=False, transient=False, image=None, ts=None, desktop=''):
        self.id = id
        self.app = app or ''
        self.summary = summary or ''
        self.body = body or ''
        self.icon = icon or ''
        self.image = image            # GdkPixbuf or None (never persisted)
        self.actions = actions        # [(key, label)]
        self.urgency = urgency
        self.timeout = timeout        # ms: -1 default, 0 never
        self.ts = ts or time.time()
        self.category = category
        self.resident = resident
        self.transient = transient
        self.desktop = desktop or ''

    def to_json(self):
        return dict(id=self.id, app=self.app, summary=self.summary, body=self.body, icon=self.icon,
                    urgency=self.urgency, ts=self.ts, category=self.category, desktop=self.desktop)

    @classmethod
    def from_json(cls, d):
        return cls(d.get('id', 0), d.get('app', ''), d.get('summary', ''), d.get('body', ''), d.get('icon', ''),
                   [], d.get('urgency', NORMAL), -1, d.get('category', ''), ts=d.get('ts'),
                   desktop=d.get('desktop', ''))

    def seconds(self):
        """How long the toast stays: None = sticky."""
        if self.timeout == 0 or self.urgency == CRITICAL and self.timeout < 0:
            return None
        if self.timeout > 0:
            return max(2.0, self.timeout / 1000.0)
        return 4.5 if self.urgency == LOW else 7.0


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False))
    os.replace(tmp, path)


def load_history(limit=150):
    try:
        data = json.loads(HISTORY.read_text())
    except (OSError, ValueError):
        return []
    return [Notif.from_json(d) for d in data[-limit:]]


def save_history(items):
    try:
        write_json(HISTORY, [n.to_json() for n in items[-150:]])
    except OSError:
        pass

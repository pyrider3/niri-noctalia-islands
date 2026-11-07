"""One independent local alarm, with atomic locked updates across UI and daemon."""
import contextlib
import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import time
import uuid

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'notion-now'

class AlarmStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else STATE

    def read(self):
        try:
            value = json.loads((self.root/'alarm.json').read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def change(self, edit):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.root/'alarm.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = self.read()
            result = edit(value)
            tmp = self.root/('alarm.'+uuid.uuid4().hex+'.tmp')
            try:
                fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w') as out:
                    json.dump(value, out, ensure_ascii=False)
                    out.flush(); os.fsync(out.fileno())
                tmp.replace(self.root/'alarm.json')
            finally:
                tmp.unlink(missing_ok=True)
            return result

    def schedule(self, due, now=None):
        now = time.time() if now is None else now
        if not math.isfinite(due) or due <= now or due > now + 366*86400:
            raise ValueError('请选择未来的时间')
        def edit(v):
            sound = v.get('sound', True)
            v.clear()
            v.update(id=uuid.uuid4().hex, due=due, created=now, status='scheduled', sound=sound)
            return v.copy()
        return self.change(edit)

    def cancel(self, alarm_id=None):
        def edit(v):
            if alarm_id is None or v.get('id') == alarm_id:
                v['status'] = 'dismissed'
        self.change(edit)

    def snooze(self, alarm_id, now=None):
        now = time.time() if now is None else now
        def edit(v):
            if v.get('id') == alarm_id and v.get('status') == 'ringing':
                v.update(id=uuid.uuid4().hex, due=now+300, created=now, status='scheduled')
        self.change(edit)

    def sound(self):
        def edit(v):
            v['sound'] = not v.get('sound', True)
        self.change(edit)

    def claim(self, now=None):
        now = time.time() if now is None else now
        def edit(v):
            if v.get('status') == 'scheduled' and isinstance(v.get('due'), (float,int)) and v['due'] <= now:
                v['status'] = 'ringing'
                return v.copy()
        return self.change(edit)


def next_time(hour, minute, tz, now=None):
    current = dt.datetime.fromtimestamp(time.time() if now is None else now, tz)
    due = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= current:
        due += dt.timedelta(days=1)
    return due.timestamp()


def countdown(alarm, now=None):
    if alarm.get('status') == 'ringing':
        return '时间到了'
    if alarm.get('status') != 'scheduled':
        return ''
    seconds = max(0, math.ceil(alarm.get('due', 0)-(time.time() if now is None else now)))
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    return f'{h:02d}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'

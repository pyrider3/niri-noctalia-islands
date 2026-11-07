"""Timer / pomodoro / stopwatch state. Everything is stored as wall-clock timestamps in timers.json, so the bar
clock (another process) can show the running state and nothing is lost when the island process restarts."""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'clock-island'
FILE = STATE / 'timers.json'
SOUND = '/usr/share/sounds/freedesktop/stereo/complete.oga'
PHASES = ('focus', 'short', 'long')
PHASE_NAME = {'focus': '专注', 'short': '短休息', 'long': '长休息'}


def read_config():
    try:
        return json.loads((STATE / 'config.json').read_text())
    except (OSError, ValueError):
        return {}


def default():
    return dict(
        sw=dict(acc=0.0, started=None, laps=[]),
        tm=dict(dur=300, left=300.0, end=None, done=False),
        pm=dict(phase='focus', left=1500.0, end=None, cycle=0, today=0, day='', done=False),
    )


def phase_len(phase):
    c = read_config()
    mins = {'focus': c.get('pomo_focus', 25), 'short': c.get('pomo_short', 5), 'long': c.get('pomo_long', 15)}[phase]
    return max(1, int(mins)) * 60.0


def beep():
    if os.path.exists(SOUND):
        try:
            p = subprocess.Popen(['paplay', '--client-name=notifd-sound', SOUND], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Thread(target=p.wait, daemon=True).start()
        except OSError:
            pass


def notify(title, body, icon='alarm-clock'):
    try:
        p = subprocess.Popen(['notify-send', '-a', '时钟', '-i', icon, title, body], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        threading.Thread(target=p.wait, daemon=True).start()
    except OSError:
        pass


class Timers:
    def __init__(self):
        self.d = default()
        try:
            saved = json.loads(FILE.read_text())
            for k in self.d:
                self.d[k].update(saved.get(k, {}))
        except (OSError, ValueError):
            pass
        self._day_check()
        self.save()

    # -------------------------------------------------------------- storage
    def save(self):
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            tmp = FILE.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.d))
            os.replace(tmp, FILE)
        except OSError:
            pass

    def _day_check(self):
        today = time.strftime('%Y-%m-%d')
        if self.d['pm'].get('day') != today:
            self.d['pm']['day'] = today
            self.d['pm']['today'] = 0

    # ------------------------------------------------------------ stopwatch
    @property
    def sw(self):
        return self.d['sw']

    def sw_elapsed(self, now=None):
        s = self.sw
        now = time.time() if now is None else now
        return s['acc'] + (now - s['started'] if s['started'] else 0.0)

    def sw_running(self):
        return self.sw['started'] is not None

    def sw_toggle(self):
        s = self.sw
        now = time.time()
        if s['started'] is None:
            s['started'] = now
        else:
            s['acc'] += now - s['started']
            s['started'] = None
        self.save()

    def sw_lap(self):
        if self.sw_running():
            self.sw['laps'].append(self.sw_elapsed())
            del self.sw['laps'][:-50]
            self.save()

    def sw_reset(self):
        self.d['sw'] = dict(acc=0.0, started=None, laps=[])
        self.save()

    # ---------------------------------------------------------------- timer
    @property
    def tm(self):
        return self.d['tm']

    def tm_left(self, now=None):
        t = self.tm
        now = time.time() if now is None else now
        return max(0.0, t['end'] - now) if t['end'] else float(t['left'])

    def tm_running(self):
        return self.tm['end'] is not None

    def tm_set(self, secs):
        t = self.tm
        t['dur'] = max(5, int(secs))
        if not self.tm_running():
            t['left'] = float(t['dur'])
            t['done'] = False
        self.save()

    def tm_adjust(self, delta):
        t = self.tm
        if self.tm_running():
            return
        self.tm_set(max(60, min(99 * 3600, t['dur'] + delta)))

    def tm_toggle(self):
        t = self.tm
        now = time.time()
        if t['end'] is None:
            if t['done'] or t['left'] <= 0:
                t['left'] = float(t['dur'])
            t['done'] = False
            t['end'] = now + t['left']
        else:
            t['left'] = max(0.0, t['end'] - now)
            t['end'] = None
        self.save()

    def tm_reset(self):
        t = self.tm
        t.update(end=None, left=float(t['dur']), done=False)
        self.save()

    # ------------------------------------------------------------- pomodoro
    @property
    def pm(self):
        return self.d['pm']

    def pm_left(self, now=None):
        p = self.pm
        now = time.time() if now is None else now
        return max(0.0, p['end'] - now) if p['end'] else float(p['left'])

    def pm_total(self):
        return phase_len(self.pm['phase'])

    def pm_running(self):
        return self.pm['end'] is not None

    def pm_toggle(self):
        p = self.pm
        now = time.time()
        if p['end'] is None:
            p['done'] = False
            p['end'] = now + p['left']
        else:
            p['left'] = max(0.0, p['end'] - now)
            p['end'] = None
        self.save()

    def _pm_goto(self, phase, run):
        p = self.pm
        p['phase'] = phase
        p['left'] = phase_len(phase)
        p['end'] = time.time() + p['left'] if run else None
        self.save()

    def pm_skip(self):
        p = self.pm
        run = self.pm_running()
        if p['phase'] == 'focus':
            nxt = 'long' if (p['cycle'] + 1) % 4 == 0 else 'short'
            p['cycle'] += 1
        else:
            nxt = 'focus'
        self._pm_goto(nxt, run)

    def pm_reset(self):
        p = self.pm
        p.update(phase='focus', cycle=0, done=False)
        self._pm_goto('focus', False)

    def pm_pick(self, phase):
        self._pm_goto(phase, False)

    # ------------------------------------------------------------------ tick
    def tick(self):
        """Call a few times a second: fires notifications when something finishes. Returns True if state changed."""
        now = time.time()
        changed = False
        t = self.tm
        if t['end'] is not None and now >= t['end']:
            t.update(end=None, left=0.0, done=True)
            notify('计时结束', '设定的 %s 已到。' % fmt_dur(t['dur']), 'alarm-clock')
            beep()
            changed = True
        p = self.pm
        if p['end'] is not None and now >= p['end']:
            self._day_check()
            if p['phase'] == 'focus':
                p['today'] += 1
                p['cycle'] += 1
                nxt = 'long' if p['cycle'] % 4 == 0 else 'short'
                notify('专注完成 🍅', '今天第 %d 个番茄。休息一下吧（%s）。' % (p['today'], PHASE_NAME[nxt]), 'appointment-soon')
            else:
                nxt = 'focus'
                notify('休息结束', '开始下一个专注吧。', 'appointment-soon')
            beep()
            self._pm_goto(nxt, bool(read_config().get('pomo_auto', True)))
            changed = True
        if changed:
            self.save()
        return changed

    def ack(self):
        if self.tm['done']:
            self.tm['done'] = False
            self.save()


def fmt_dur(secs):
    secs = int(secs)
    if secs >= 3600:
        return '%d 小时 %d 分' % (secs // 3600, secs % 3600 // 60) if secs % 3600 else '%d 小时' % (secs // 3600)
    if secs % 60 == 0:
        return '%d 分钟' % (secs // 60)
    return '%d 分 %d 秒' % (secs // 60, secs % 60)


def fmt_clock(secs):
    secs = max(0, int(secs + .999))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return '%d:%02d:%02d' % (h, m, s) if h else '%02d:%02d' % (m, s)

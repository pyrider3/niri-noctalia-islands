#!/usr/bin/env python3
"""Bar clock: rolling digits, breathing colon, cute sun/moon face (cairo, streamed to the bar widget)."""
import json
import math
import os
import random
import sys
import time
from pathlib import Path

import cairo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cute  # noqa: E402
import timers as TM  # noqa: E402
import weather as WX  # noqa: E402

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'clock-island'
THEME = Path.home() / '.local/state/status-capsule/input.json'
H = 28
MAXW = 150
SCALE = 2
FONT = 'Noto Sans CJK SC'
ICON_W = 24


def read_json(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def save_json(p, v):
    try:
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(v))
        os.replace(tmp, p)
    except OSError:
        pass


def clamp01(v):
    return max(0.0, min(1.0, v))


def rgb(h, fb):
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (TypeError, ValueError, IndexError):
        return fb


class Spring:
    def __init__(self, x=0.0, omega=26.0, zeta=.55):
        self.x = self.t = float(x)
        self.v = 0.0
        self.o, self.z = omega, zeta

    def step(self, dt):
        dt = min(.05, max(0.0, dt))
        n = int(dt / .004) + 1
        h = dt / n
        for _ in range(n):
            self.v += (-2 * self.z * self.o * self.v - self.o * self.o * (self.x - self.t)) * h
            self.x += self.v * h
        if abs(self.x - self.t) < .004 and abs(self.v) < .01:
            self.x, self.v = self.t, 0.0

    @property
    def moving(self):
        return self.x != self.t or self.v != 0.0


class Slot:
    """One rolling digit."""

    def __init__(self, ch):
        self.cur = self.prev = ch
        self.r = Spring(1, omega=24, zeta=.5)

    def set(self, ch):
        if ch != self.cur:
            self.prev, self.cur = self.cur, ch
            self.r.x, self.r.v, self.r.t = 0.0, 0.0, 1.0


class Clock:
    def __init__(self):
        now = time.localtime()
        self.slots = {k: Slot('0') for k in ('h1', 'h2', 'm1', 'm2', 's1', 's2')}
        self.width = Spring(70, omega=24, zeta=.7)
        self.hop = Spring(0, omega=30, zeta=.3)
        self.sun = Spring(0, omega=10, zeta=1.0)
        self.t = 0.0
        self.blink_at = time.monotonic() + 2
        self.blink_len = .16
        self.show_s = False
        self.theme = {}
        self.theme_t = 0.0
        self.last_min = None
        self.cw = 70
        self.last_status = 0.0
        self.last_draw = 0.0
        self.cfg_t = 0.0
        self.sec_a = Spring(0, omega=20, zeta=1.0)
        self.ind_a = Spring(0, omega=22, zeta=.7)
        self.ind = None            # running timer/pomodoro/stopwatch summary shown beside the time
        self.last_ind = None
        self.tj = {}
        self.wx = WX.read()
        self.wx_t = time.monotonic()
        self.tj_t = 0.0
        self.cfg = {}
        self._scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        self.sun.x = self.sun.t = cute.sun_amount(now.tm_hour + now.tm_min / 60)
        self._tick_digits(first=True)

    def _digits(self):
        n = time.localtime()
        return n, '%02d' % n.tm_hour, '%02d' % n.tm_min, '%02d' % n.tm_sec

    def _tick_digits(self, first=False):
        n, hh, mm, ss = self._digits()
        for key, ch in (('h1', hh[0]), ('h2', hh[1]), ('m1', mm[0]), ('m2', mm[1]), ('s1', ss[0]), ('s2', ss[1])):
            if first:
                self.slots[key].cur = self.slots[key].prev = ch
            else:
                self.slots[key].set(ch)
        key = (n.tm_hour, n.tm_min)
        if self.last_min is not None and key != self.last_min:
            self.hop.x, self.hop.v = -.9, 0.0
            self.blink_at = time.monotonic()
        self.last_min = key
        return n

    def _indicator(self):
        d = self.tj
        now = time.time()
        pm, tm, sw = d.get('pm', {}), d.get('tm', {}), d.get('sw', {})
        if pm.get('end'):
            mins = {'focus': self.cfg.get('pomo_focus', 25), 'short': self.cfg.get('pomo_short', 5),
                    'long': self.cfg.get('pomo_long', 15)}.get(pm.get('phase'), 25)
            left = max(0.0, pm['end'] - now)
            col = {'focus': (1.0, .42, .34), 'short': (.38, .82, .5), 'long': (.42, .62, 1.0)}.get(pm.get('phase'), (1, .42, .34))
            return dict(kind='pm', frac=left / max(1.0, mins * 60.0), text=TM.fmt_clock(left), col=col)
        if tm.get('end'):
            left = max(0.0, tm['end'] - now)
            return dict(kind='tm', frac=left / max(1.0, float(tm.get('dur', 1))), text=TM.fmt_clock(left), col=None)
        if tm.get('done'):
            return dict(kind='done', frac=1.0, text='时间到', col=(1.0, .4, .4))
        if sw.get('started'):
            el = sw.get('acc', 0.0) + now - sw['started']
            return dict(kind='sw', frac=(el % 60) / 60.0, text=TM.fmt_clock(el - .999) if el >= 1 else '00:00', col=(1.0, .78, .3))
        return None

    def step(self, delta, now):
        mono = time.monotonic()
        if mono - self.tj_t > .2:
            self.tj_t = mono
            self.tj = read_json(STATE / 'timers.json')
            self.cfg = read_json(STATE / 'config.json')
        if mono - self.wx_t > 30:
            self.wx_t = mono
            self.wx = WX.read()
        ind = self._indicator()
        if ind is not None:
            self.ind = self.last_ind = ind
        else:
            self.ind = None
        self.ind_a.t = 1.0 if self.ind else 0.0
        if mono - self.theme_t > 2:
            self.theme_t = mono
            self.theme = read_json(THEME)
        if mono - self.cfg_t > .5:
            self.cfg_t = mono
            self.show_s = bool(read_json(STATE / 'config.json').get('show_seconds', False))
        n = self._tick_digits()
        self.t += delta
        self.sun.t = cute.sun_amount(n.tm_hour + n.tm_min / 60)
        self.sec_a.t = 1.0 if self.show_s else 0.0
        char_w = 8.4
        ind_w = 0.0
        li = self.ind or self.last_ind
        if li:
            self._scratch.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            self._scratch.set_font_size(10.5)
            ind_w = 7 + 13 + 3 + self._scratch.text_extents(li['text']).x_advance
        self.width.t = ICON_W + 5 + char_w * 4 + 4.2 + 17.0 * self.sec_a.x + 1 + ind_w * clamp01(self.ind_a.x)
        moving = False
        for sp in [self.width, self.hop, self.sun, self.sec_a, self.ind_a] + [s.r for s in self.slots.values()]:
            sp.step(delta)
            moving = moving or sp.moving
        self.cw = max(40, min(MAXW, int(math.ceil(self.width.x))))
        blinking = mono - self.blink_at < self.blink_len
        if mono > self.blink_at + self.blink_len:
            self.blink_at = mono + random.uniform(2.5, 6.0)
        # the sun's rays turn slowly: redraw ~20 fps when nothing else moves
        if moving or blinking:
            self.last_draw = mono
            return True
        if mono - self.last_draw > .05:
            self.last_draw = mono
            return True
        return False

    # ---------------------------------------------------------------- drawing
    def _digit(self, c, slot, x, size, text, alpha, cell_w, baseline):
        r = slot.r.x
        rr = max(-.3, min(1.3, r))
        c.save()
        c.rectangle(x - 1, 0, cell_w + 2, H)
        c.clip()
        c.set_font_size(size)
        # leaving digit goes up, new one rises from below with a little overshoot
        if rr < .999 and slot.prev != slot.cur:
            c.set_source_rgba(*text, alpha * max(0.0, 1 - rr * 1.6))
            ext = c.text_extents(slot.prev)
            c.move_to(x + (cell_w - ext.x_advance) / 2, baseline - rr * 9)
            c.show_text(slot.prev)
        c.set_source_rgba(*text, alpha * min(1.0, rr * 1.6 + .001 if slot.prev != slot.cur else 1.0))
        ext = c.text_extents(slot.cur)
        c.move_to(x + (cell_w - ext.x_advance) / 2, baseline + (1 - rr) * 9)
        c.show_text(slot.cur)
        c.restore()

    def render(self):
        cw = self.cw
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, cw * SCALE, H * SCALE)
        c = cairo.Context(surf)
        c.scale(SCALE, SCALE)
        text = rgb(self.theme.get('text'), (.96, .96, .96))
        n = time.localtime()
        hour = n.tm_hour + n.tm_min / 60
        mono = time.monotonic()
        blink = 0.0
        if mono - self.blink_at < self.blink_len and mono >= self.blink_at:
            p = (mono - self.blink_at) / self.blink_len
            blink = math.sin(p * math.pi) * .9
        # icon, hopping each minute
        hop = self.hop.x
        c.save()
        draw_y = H / 2 + hop * 2.2
        cute.draw_condition(c, ICON_W / 2 + 1, draw_y, 8.4, self.t, self.wx['cond'] if self.wx else 'clear',
                            max(0.0, min(1.0, self.sun.x)), blink, hour)
        c.restore()
        # digits
        c.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cell, size, base = 8.4, 14.5, H / 2 + 5.2
        x = ICON_W + 5
        for key in ('h1', 'h2'):
            self._digit(c, self.slots[key], x, size, text, 1.0, cell, base)
            x += cell
        # breathing colon
        frac = time.time() % 1.0
        ca = .5 + .5 * math.cos(frac * math.tau) if self.show_s else .62 + .38 * math.sin(self.t * 2.4)
        c.set_source_rgba(*text, .35 + .65 * ca)
        c.arc(x + 2.1, H / 2 - 3.1, 1.15, 0, math.tau)
        c.fill()
        c.arc(x + 2.1, H / 2 + 3.1, 1.15, 0, math.tau)
        c.fill()
        x += 4.2
        for key in ('m1', 'm2'):
            self._digit(c, self.slots[key], x, size, text, 1.0, cell, base)
            x += cell
        sa = self.sec_a.x
        if sa > .02:
            x += 1.5
            for key in ('s1', 's2'):
                self._digit(c, self.slots[key], x, 10.5, text, .62 * min(1.0, sa), 6.2, base - .3)
                x += 6.2
        ia = clamp01(self.ind_a.x)
        li = self.ind or self.last_ind
        if li and ia > .02:
            x += 7
            col = li['col'] or rgb(self.theme.get('accent'), (.21, .52, .89))
            done = li['kind'] == 'done'
            pulse = (.55 + .45 * math.sin(self.t * 7)) if done else 1.0
            cx, cy, r = x + 6.5, H / 2, 5.4
            c.set_line_width(2.0)
            c.set_line_cap(1)
            c.new_path()
            c.arc(cx, cy, r, 0, math.tau)
            c.set_source_rgba(*text, .22 * ia)
            c.stroke()
            c.new_path()
            if li['kind'] == 'sw':
                a0 = -math.pi / 2 + self.t * 3
                c.arc(cx, cy, r, a0, a0 + 1.6)
            else:
                c.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + math.tau * max(.02, min(1.0, li['frac'])))
            c.set_source_rgba(*col, ia * pulse)
            c.stroke()
            c.set_font_size(10.5)
            c.set_source_rgba(*(col if done else text), .9 * ia * (pulse if done else 1))
            c.move_to(x + 13 + 3, base - .4)
            c.show_text(li['text'])
        raw = memoryview(surf.get_data()).cast('B')
        return surf, raw

    def paint(self):
        surf, raw = self.render()
        out = bytearray(raw)
        out[0::4] = raw[2::4]
        out[2::4] = raw[0::4]
        now = time.time()
        if now - self.last_status > 1 or self.cw != getattr(self, '_last_cw', None):
            self._last_cw = self.cw
            self.last_status = now
            save_json(STATE / 'status.json', dict(updated=now, width=self.cw))
        return self.cw, bytes(out)


if __name__ == '__main__':
    from stream_server import serve
    serve(Clock, STATE, 'canvas', MAXW, H, headless=True)

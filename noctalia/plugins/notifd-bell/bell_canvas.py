#!/usr/bin/env python3
"""Animated notification bell for the bar (cairo, streamed to the bar widget)."""
import json
import math
import os
import time
from pathlib import Path

import cairo

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'notifd-bell'
NOTIFD_STATE = Path.home() / '.local/state/notifd/state.json'
THEME = Path.home() / '.local/state/status-capsule/input.json'
W = H = 28
MAXW = 380
KICK = Path.home() / '.local/state/notifd/bell-kick.json'
CURRENT = Path.home() / '.local/state/notifd/current.json'
SCALE = 2
BELL_SCALE = .8     # glyph size relative to the other bar icons
TAU = 2 * math.pi


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


def rgb(h, fb):
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (TypeError, ValueError):
        return fb


class Spring:
    def __init__(self, x=0.0, omega=30.0, zeta=.45):
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
        if abs(self.x - self.t) < .005 and abs(self.v) < .02:
            self.x, self.v = self.t, 0.0

    @property
    def moving(self):
        return self.x != self.t or self.v != 0.0


class Bell:
    def __init__(self):
        self.unread = 0
        self.count = 0
        self.dnd = False
        self.prev_unread = 0
        self.mtime = None
        self.theme = {}
        self.theme_t = 0.0
        self.ring_at = -10.0          # time of the last ring
        self.next_reminder = time.monotonic() + 8
        self.pop = Spring(0, omega=34, zeta=.42)    # badge pop
        self.pop.t = 0
        self.bump = Spring(0, omega=38, zeta=.34)
        self.kick_seq = None
        self.badge_on = Spring(0, omega=28, zeta=.55)
        self.dnd_mix = Spring(0, omega=26, zeta=1.0)
        self.t = 0.0
        self.last_status = 0.0
        # in-bar capsule (notifd "capsule" style)
        self.cur = {}
        self.cur_mtime = None
        self.width = Spring(W, omega=26, zeta=.6)
        self.width.t = W
        self.cw = W
        self.icon_key = None
        self.icon_surf = None
        self.icon_dom = None
        self._scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))

    def read(self):
        try:
            mt = NOTIFD_STATE.stat().st_mtime_ns
        except OSError:
            return
        if mt == self.mtime:
            return
        self.mtime = mt
        s = read_json(NOTIFD_STATE)
        self.count = int(s.get('count', 0))
        self.dnd = bool(s.get('dnd', False))
        unread = int(s.get('unread', 0))
        now = time.monotonic()
        if unread > self.unread and not self.dnd:
            self.ring_at = now                    # new notification: ring
            self.pop.x = 1.6                      # badge overshoots, then settles
            self.pop.t = 1.0
        self.unread = unread

    # ------------------------------------------------------------- capsule
    def read_current(self):
        try:
            mt = CURRENT.stat().st_mtime_ns
        except OSError:
            self.cur = {}
            return
        if mt != self.cur_mtime:
            self.cur_mtime = mt
            self.cur = read_json(CURRENT)
        # a stale file (notifd gone) must never leave the capsule stretched
        if self.cur.get('active') and time.time() - float(self.cur.get('t', 0)) > 3:
            self.cur = {}

    def capsule_active(self):
        return bool(self.cur.get('active')) and not self.dnd

    def text_w(self, s, size, bold):
        c = self._scratch
        c.select_font_face('Noto Sans CJK SC', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size)
        return c.text_extents(s).x_advance

    def target_width(self):
        if not self.capsule_active():
            return W
        title, body = self.cur.get('summary', ''), self.cur.get('body', '')
        tw = self.text_w(title, 12.5, True)
        bw = min(self.text_w(body, 11.5, False), 170) if body else 0
        extra = (12 + bw) if body else 0
        return max(150, min(MAXW, 38 + tw + extra + 18))

    def load_icon(self):
        key = (self.cur.get('id'), self.cur.get('icon'))
        if key == self.icon_key:
            return
        self.icon_key = key
        self.icon_surf, self.icon_dom = None, None
        try:
            surf = cairo.ImageSurface.create_from_png(self.cur.get('icon', ''))
        except Exception:
            return
        self.icon_surf = surf
        # dominant colour for the glow
        w, h, st = surf.get_width(), surf.get_height(), surf.get_stride()
        d = bytes(surf.get_data())
        sr = sg = sb = sw = 0.0
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                i = y * st + x * 4
                b, g, r, a = d[i], d[i + 1], d[i + 2], d[i + 3]
                if a < 40:
                    continue
                r, g, b = (min(255, v * 255 // a) for v in (r, g, b))
                mx, mn = max(r, g, b), min(r, g, b)
                wgt = (a / 255) * (((mx - mn) / (mx + 1)) ** 2 + .03) * (mx / 255 + .2)
                sr += r * wgt; sg += g * wgt; sb += b * wgt; sw += wgt
        if sw > 0:
            c = (sr / sw / 255, sg / sw / 255, sb / sw / 255)
            m = max(c) or 1
            self.icon_dom = tuple(min(1, v / m * .92) for v in c)

    def read_kick(self):
        try:
            d = read_json(KICK)
            seq = int(d.get('seq', 0))
        except (OSError, ValueError, TypeError):
            return
        if self.kick_seq is None:
            self.kick_seq = seq
            return
        if seq != self.kick_seq:
            self.kick_seq = seq
            if time.time() - float(d.get('t', 0)) < 1.5:
                self.ring_at = time.monotonic()
                self.bump.x = .55 * float(d.get('s', 1.0))
                self.bump.v = 0.0

    def step(self, delta, now):
        self.read_kick()
        self.read()
        self.read_current()
        self.width.t = self.target_width()
        self.width.step(delta)
        self.cw = max(W, int(round(self.width.x)))
        mono = time.monotonic()
        if mono - self.theme_t > 2:
            self.theme_t = mono
            self.theme = read_json(THEME)
        self.t += delta
        if self.unread > 0 and not self.dnd and mono > self.next_reminder:
            self.ring_at = mono                   # gentle reminder while unread
            self.next_reminder = mono + 9
        self.badge_on.t = 1.0 if (self.unread > 0 and not self.dnd) else 0.0
        self.dnd_mix.t = 1.0 if self.dnd else 0.0
        self.bump.step(delta)
        for sp in (self.pop, self.badge_on, self.dnd_mix):
            sp.step(delta)
        ringing = mono - self.ring_at < 1.6
        return (ringing or self.bump.moving or self.pop.moving or self.badge_on.moving or self.dnd_mix.moving or self.dnd
                or self.width.moving or self.capsule_active())

    def render(self):
        cw = self.cw
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, cw * SCALE, H * SCALE)
        c = cairo.Context(surf)
        c.scale(SCALE, SCALE)
        cap = max(0.0, min(1.0, (self.width.x - W - 6) / 50))   # 0 = plain bell .. 1 = stretched capsule
        th = self.theme
        text = rgb(th.get('text'), (.95, .95, .95))
        accent = rgb(th.get('accent'), (.21, .52, .89))
        danger = (1.0, .38, .4)
        mono = time.monotonic()
        age = mono - self.ring_at
        dm = max(0.0, min(1.0, self.dnd_mix.x))
        c.push_group()
        if dm < .98:
            c.save()
            c.translate(W / 2, H / 2 + .5)
            c.set_source_rgba(*text, 1 - dm)
            # swing: damped oscillation after a ring, tiny idle sway otherwise
            rot = math.sin(age * 26) * .42 * math.exp(-age * 3.0) if age < 1.6 else math.sin(self.t * 1.3) * .015
            c.save()
            c.translate(0, -8)
            c.rotate(rot)
            c.translate(0, 8)
            bs = (1 + max(-.3, self.bump.x) * .35) * BELL_SCALE
            c.scale(bs, bs)
            self.bell(c, filled=self.unread > 0, accent=accent, text=text, swing=rot)
            c.restore()
            c.restore()
        if dm > .02:
            self.moon(c, text, accent, dm)
        b = max(0.0, self.badge_on.x)
        if b > .02:
            s = max(0.0, b) * (1 + .0 * self.pop.x)
            pop = self.pop.x if self.pop.x > 0 else 1.0
            r = 6.1 * min(1.0, b) * (pop if pop > 0 else 1.0)
            bx, by = 20.2, 7.8
            c.set_source_rgba(0, 0, 0, .25)
            c.arc(bx, by + .8, r + .6, 0, TAU)
            c.fill()
            c.set_source_rgb(*danger)
            c.arc(bx, by, r, 0, TAU)
            c.fill()
            c.select_font_face('Noto Sans CJK SC', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            label = str(self.unread) if self.unread < 10 else '9+'
            c.set_font_size(8.2 if self.unread < 10 else 6.4)
            ext = c.text_extents(label)
            c.set_source_rgb(1, 1, 1)
            c.move_to(bx - ext.x_advance / 2, by + ext.height / 2 - .2)
            c.show_text(label)
        c.pop_group_to_source()
        c.paint_with_alpha(1 - cap)
        if cap > .01 and self.cur.get('active'):
            self.capsule(c, cw, cap, text, accent, danger)
        surf.flush()
        return surf

    def fit(self, c, s, maxw):
        if c.text_extents(s).x_advance <= maxw:
            return s
        while len(s) > 1 and c.text_extents(s + '…').x_advance > maxw:
            s = s[:-1]
        return s + '…'

    def capsule(self, c, w, cap, text, accent, danger):
        cur = self.cur
        self.load_icon()
        crit = cur.get('urgency') == 2
        col = danger if crit else accent
        c.push_group()
        c.save()
        r = H / 2
        c.new_sub_path()
        c.arc(r, r, r, math.pi / 2, 3 * math.pi / 2)
        c.arc(w - r, r, r, -math.pi / 2, math.pi / 2)
        c.close_path()
        c.clip()
        dom = self.icon_dom or col
        g = cairo.RadialGradient(16, 14, 2, 16, 14, 190)
        g.add_color_stop_rgba(0, *dom, .34)
        g.add_color_stop_rgba(1, *dom, 0)
        c.set_source(g)
        c.paint()
        cx, cy = 18, 14
        c.set_line_width(2)
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        c.arc(cx, cy, 12.6, 0, TAU)
        c.set_source_rgba(*text, .14)
        c.stroke()
        total = float(cur.get('total') or 0)
        if total > 0:
            rem = float(cur.get('remaining', total))
            if not cur.get('paused'):
                rem -= time.time() - float(cur.get('t', time.time()))
            frac = max(0.0, min(1.0, rem / total))
            c.arc(cx, cy, 12.6, -math.pi / 2, -math.pi / 2 + TAU * frac)
            c.set_source_rgb(*col)
            c.stroke()
        if self.icon_surf is not None:
            sw_, sh_ = self.icon_surf.get_width(), self.icon_surf.get_height()
            k = 17.0 / max(sw_, sh_)
            c.save()
            c.translate(cx - sw_ * k / 2, cy - sh_ * k / 2)
            c.scale(k, k)
            c.set_source_surface(self.icon_surf, 0, 0)
            c.paint()
            c.restore()
        c.select_font_face('Noto Sans CJK SC', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        c.set_font_size(12.5)
        title = cur.get('summary', '')
        avail = w - 38 - 14
        c.set_source_rgba(*text, 1)
        tfit = self.fit(c, title, avail)
        c.move_to(38, 18.2)
        c.show_text(tfit)
        body = cur.get('body', '')
        if body:
            tw = c.text_extents(tfit).x_advance
            room = avail - tw - 12
            if room > 40:
                c.select_font_face('Noto Sans CJK SC', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                c.set_font_size(11.5)
                c.set_source_rgba(*text, .66)
                c.move_to(38 + tw + 12, 18)
                c.show_text(self.fit(c, body, room))
        c.restore()
        c.pop_group_to_source()
        c.paint_with_alpha(cap)

    def bell(self, c, filled, accent, text, swing):
        # dome + flared rim
        def path():
            c.move_to(-7.2, 5.4)
            c.curve_to(-5.2, 4.0, -4.4, 1.2, -4.4, -1.8)
            c.curve_to(-4.4, -5.4, -2.2, -7.2, 0, -7.2)
            c.curve_to(2.2, -7.2, 4.4, -5.4, 4.4, -1.8)
            c.curve_to(4.4, 1.2, 5.2, 4.0, 7.2, 5.4)
            c.close_path()
        c.set_line_width(1.6 / BELL_SCALE * .86)
        c.set_line_join(cairo.LINE_JOIN_ROUND)
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        path()
        if filled:
            c.set_source_rgb(*accent)
            c.fill_preserve()
            c.set_source_rgb(*accent)
            c.stroke()
        else:
            c.set_source_rgb(*text)
            c.stroke()
        # knob on top
        c.arc(0, -8.4, 1.0, 0, TAU)
        c.set_source_rgb(*(accent if filled else text))
        c.fill()
        # clapper swings the opposite way. It is also the position marker: drawn in the glyph colour with the
        # blue channel off by one, so notifd can find the bell on screen by exact pixels without anything visible.
        base = accent if filled else text
        q = [int(round(v * 255)) for v in base]
        q[2] = q[2] - 1 if q[2] > 0 else 1
        self.marker = q
        c.arc(-swing * 7.5, 7.4, 2.6, 0, TAU)
        c.set_source_rgb(*[v / 255 for v in q])
        c.fill()

    def moon(self, c, text, accent, dm):
        t = time.monotonic()
        c.save()
        c.translate(W / 2 - .5, H / 2 + .5)
        c.scale(.85 + .15 * dm, .85 + .15 * dm)
        c.set_source_rgba(*text, .95 * dm)
        c.arc(0, 0, 7, 0, TAU)
        c.fill()
        c.set_operator(cairo.OPERATOR_CLEAR)
        c.arc(3.6, -2.6, 6.2, 0, TAU)
        c.fill()
        c.set_operator(cairo.OPERATOR_OVER)
        for i, (sx, sy, ph) in enumerate(((7.5, -6.5, 0), (9.5, 2.5, 1.9), (4.5, 8.5, 3.7))):
            s = (math.sin(t * 2.4 + ph) + 1) / 2
            r = .8 + 2.0 * s
            c.save()
            c.translate(sx, sy)
            c.rotate(t * .7 + i)
            c.set_source_rgba(*accent, (.25 + .75 * s) * dm)
            c.move_to(0, -r); c.line_to(r * .3, -r * .3); c.line_to(r, 0); c.line_to(r * .3, r * .3)
            c.line_to(0, r); c.line_to(-r * .3, r * .3); c.line_to(-r, 0); c.line_to(-r * .3, -r * .3)
            c.close_path()
            c.fill()
            c.restore()
        c.restore()

    def paint(self):
        surf = self.render()
        raw = memoryview(surf.get_data()).cast('B')
        out = bytearray(raw)
        out[0::4] = raw[2::4]
        out[2::4] = raw[0::4]
        now = time.time()
        if now - self.last_status > 1 or self.cw != getattr(self, '_last_cw', None):
            self._last_cw = self.cw
            self.last_status = now
            save_json(STATE / 'status.json', dict(updated=now, width=self.cw, marker=getattr(self, 'marker', None)))
        return self.cw, bytes(out)


if __name__ == '__main__':
    from stream_server import serve
    serve(Bell, STATE, 'canvas', MAXW, H, headless=True)

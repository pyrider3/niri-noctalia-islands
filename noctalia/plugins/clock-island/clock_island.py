#!/usr/bin/env python3
"""Dynamic-island calendar: the bar clock capsule morphs into a black island holding a month calendar.

Run by the bar widget (widget.luau); commands arrive through ~/.local/state/clock-island/cmd.json.
"""
import calendar
import datetime as dt
import fcntl
import json
import math
import os
import sys
import time
from pathlib import Path

_LAYER = '/usr/lib/libgtk4-layer-shell.so'
if _LAYER not in os.environ.get('LD_PRELOAD', '') and os.path.exists(_LAYER):
    _env = dict(os.environ, LD_PRELOAD=(_LAYER + ' ' + os.environ.get('LD_PRELOAD', '')).strip())
    _env.setdefault('GSK_RENDERER', 'gl')
    os.execvpe(sys.executable, [sys.executable] + sys.argv, _env)
os.environ.setdefault('GSK_RENDERER', 'gl')

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path.home() / '.config/notifd'))   # shared text/spring helpers

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

import cute  # noqa: E402
import timers as T  # noqa: E402
import weather as WX  # noqa: E402
import gfx  # noqa: E402
from gfx import THEME, Spring, clamp, lerp, rrect  # noqa: E402

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'clock-island'

# the clock capsule in the bar (layout px) - where the island grows from
CAP_X, CAP_Y, CAP_H, CAP_PAD = 24.0, 7.0, 26.0, 6.5
# the open island
EX, EY, EW, EH = 10.0, 4.0, 372.0, 504.0
WIN_W, WIN_H = 420, 570
COLS = 7
GRID_X, GRID_Y, ROW_H = 16.0, 206.0, 36.0
WEEK = ['一', '二', '三', '四', '五', '六', '日']
BLACK = (.012, .012, .018)


def read_json(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def ctext(cr, s, size, bold, cx, cy, rgba):
    lay = gfx.text_layout(s, size, bold)
    w, h = gfx.text_size(lay)
    dl(cr, lay, cx - w / 2, cy - h / 2, rgba)


_glyph_cache = {}


def mask_text(cr, s, size, bold, cx, cy, rgba):
    """Centred text painted from a cached 2x alpha bitmap (cheap to scale/animate, unlike live glyphs)."""
    key = (s, size, bold)
    ent = _glyph_cache.get(key)
    if ent is None:
        lay = gfx.make_layout(s, size, bold)
        w, h = gfx.text_size(lay)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(w + 4) * 2, int(h + 4) * 2)
        surf.set_device_scale(2, 2)
        c = cairo.Context(surf)
        gfx.draw_layout(c, lay, 2, 2, (1, 1, 1, 1))
        ent = _glyph_cache[key] = (surf, w, h)
    surf, w, h = ent
    cr.set_source_rgba(*rgba)
    cr.mask_surface(surf, cx - w / 2 - 2, cy - h / 2 - 2)


def dl(cr, lay, x, y, rgba):
    """Like gfx.draw_layout, but paints a cached alpha bitmap so animated (scaled/faded) text stays cheap."""
    key = (lay.get_text(), lay.get_font_description().to_string(), lay.get_width())
    ent = _glyph_cache.get(key)
    if ent is None:
        if len(_glyph_cache) > 400:
            _glyph_cache.clear()
        w, h = gfx.text_size(lay)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(w + 4) * 2, int(h + 4) * 2)
        surf.set_device_scale(2, 2)
        c = cairo.Context(surf)
        gfx.draw_layout(c, lay, 2, 2, (1, 1, 1, 1))
        ent = _glyph_cache[key] = surf
    cr.set_source_rgba(*rgba)
    cr.mask_surface(ent, x - 2, y - 2)


def ease_back(t):
    t = clamp(t)
    c1, c3 = 1.9, 2.9
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2




def live(cr, s, size, bold, cx, cy, rgba, left=False):
    """Uncached text for strings that change every frame (stopwatch digits)."""
    lay = gfx.text_layout(s, size, bold)
    w, h = gfx.text_size(lay)
    gfx.draw_layout(cr, lay, cx if left else cx - w / 2, cy - h / 2, rgba)


PAGES = ['日历', '计时器', '番茄钟', '秒表']
PHASE_COL = {'focus': (1.0, .42, .34), 'short': (.38, .82, .5), 'long': (.42, .62, 1.0)}
SW_COL = (1.0, .78, .3)
RING_C = (EW / 2, 268.0)
RING_R = 82.0


# ------------------------------------------------------------- small icons
def icon_play(cr, cx, cy, s, col):
    cr.set_source_rgba(*col)
    cr.move_to(cx - s * .32, cy - s * .5)
    cr.line_to(cx + s * .56, cy)
    cr.line_to(cx - s * .32, cy + s * .5)
    cr.close_path()
    cr.fill()


def icon_pause(cr, cx, cy, s, col):
    cr.set_source_rgba(*col)
    for dx in (-.3, .3):
        rrect(cr, cx + dx * s - s * .15, cy - s * .45, s * .3, s * .9, s * .08)
        cr.fill()


def icon_reset(cr, cx, cy, s, col):
    cr.set_source_rgba(*col)
    cr.set_line_width(max(1.6, s * .17))
    cr.set_line_cap(1)
    cr.arc(cx, cy, s * .42, math.pi * .15, math.pi * 1.75)
    cr.stroke()
    a = math.pi * 1.75
    px, py = cx + math.cos(a) * s * .42, cy + math.sin(a) * s * .42
    cr.move_to(px - s * .02, py - s * .3)
    cr.line_to(px, py)
    cr.line_to(px + s * .3, py - s * .05)
    cr.stroke()


def icon_skip(cr, cx, cy, s, col):
    cr.set_source_rgba(*col)
    cr.move_to(cx - s * .38, cy - s * .42)
    cr.line_to(cx + s * .22, cy)
    cr.line_to(cx - s * .38, cy + s * .42)
    cr.close_path()
    cr.fill()
    rrect(cr, cx + s * .26, cy - s * .42, s * .15, s * .84, s * .05)
    cr.fill()


def icon_flag(cr, cx, cy, s, col):
    cr.set_source_rgba(*col)
    cr.set_line_width(max(1.6, s * .15))
    cr.set_line_cap(1)
    cr.move_to(cx - s * .3, cy + s * .5)
    cr.line_to(cx - s * .3, cy - s * .5)
    cr.stroke()
    cr.move_to(cx - s * .3, cy - s * .48)
    cr.curve_to(cx + s * .05, cy - s * .62, cx + s * .05, cy - s * .12, cx + s * .42, cy - s * .26)
    cr.line_to(cx + s * .42, cy + s * .08)
    cr.curve_to(cx + s * .05, cy + s * .2, cx + s * .05, cy - s * .3, cx - s * .3, cy - s * .12)
    cr.close_path()
    cr.fill()


def icon_plus(cr, cx, cy, s, col, minus=False):
    cr.set_source_rgba(*col)
    cr.set_line_width(max(1.6, s * .16))
    cr.set_line_cap(1)
    cr.move_to(cx - s * .38, cy)
    cr.line_to(cx + s * .38, cy)
    if not minus:
        cr.move_to(cx, cy - s * .38)
        cr.line_to(cx, cy + s * .38)
    cr.stroke()


class Island:
    def __init__(self, app):
        self.app = app
        self.win = self.catcher = None
        self.is_open = False
        self.cap_w = 70.0
        self.show_s = False
        self.wx = WX.read()
        GLib.timeout_add_seconds(30, lambda: setattr(self, 'wx', WX.read()) or True)
        self.timers = T.Timers()
        self.pw = Spring(0, omega=16, zeta=.62)
        self.ph = Spring(0, omega=12.5, zeta=.68)
        self.pp = Spring(0, omega=15, zeta=.7)
        self.ca = Spring(0, omega=18, zeta=1.0)
        self.slide = Spring(1, omega=16, zeta=.72)
        self.slide_dir = 1
        self.tpop = Spring(0, omega=22, zeta=.38)
        self.page = Spring(0, omega=17, zeta=.78)
        self.page_i = 0
        self.press_pop = {}          # zone key -> Spring (button press feedback)
        self.open_t = 0.0
        self.t = 0.0
        today = dt.date.today()
        self.view = (today.year, today.month)
        self.selected = today
        self.pointer = None
        self.zones = []
        self.blink_at = time.monotonic() + 2
        self.frame_tick = None
        self._fl = None
        self.region_key = None
        self.cmd_seq = read_json(STATE / 'cmd.json').get('seq')    # leftovers from before we started are ignored
        GLib.timeout_add(1500, self._prewarm)
        GLib.timeout_add(50, self._poll)
        GLib.timeout_add(250, self._tick_timers)
        GLib.timeout_add(1000, self._beat)
        self._beat()

    def _prewarm(self):
        """Create the windows and GL context once, invisibly, so the first open is not slow."""
        if self.is_open or self.win is not None:
            return False
        self._ensure_windows()
        self.win.present()

        def hush():
            surface = self.win.get_surface()
            if surface is not None:
                surface.set_input_region(cairo.Region())
        GLib.timeout_add(30, lambda: hush() or False)
        GLib.timeout_add(700, lambda: (self.win.set_visible(False) if not self.is_open else None) or False)
        return False

    # -------------------------------------------------------------- commands
    def _beat(self):
        try:
            tmp = STATE / 'alive.tmp'
            tmp.write_text(json.dumps(dict(t=time.time(), open=self.is_open)))
            os.replace(tmp, STATE / 'alive.json')
        except OSError:
            pass
        return True

    def _tick_timers(self):
        try:
            if self.timers.tick() and self.is_open:
                self._start_frames()
        except Exception:
            pass
        return True

    def _poll(self):
        try:
            d = json.loads((STATE / 'cmd.json').read_text())
        except (OSError, ValueError):
            return True            # missing or half-written: look again next tick
        seq = d.get('seq')
        if seq is None or seq == self.cmd_seq:
            return True
        self.cmd_seq = seq
        cmd = d.get('cmd')
        if cmd == 'toggle':
            self.close() if self.is_open else self.open()
        elif cmd == 'open':
            self.open()
        elif cmd == 'close':
            self.close()
        elif cmd == 'today':
            if not self.is_open:
                self.open()
            self.goto_today()
        elif cmd in ('timer', 'pomodoro', 'stopwatch'):
            self.open(page={'timer': 1, 'pomodoro': 2, 'stopwatch': 3}[cmd])
        return True

    # ---------------------------------------------------------------- state
    def open(self, page=None):
        if self.is_open:
            if page is not None:
                self.set_page(page)
            return
        st = read_json(STATE / 'status.json')
        self.cap_w = float(st.get('width', 70)) + 2 * CAP_PAD
        self.show_s = bool(read_json(STATE / 'config.json').get('show_seconds', False))
        self._ensure_windows()
        today = dt.date.today()
        self.view = (today.year, today.month)
        self.selected = today
        self.slide.snap(1)
        self.tpop.snap(0)
        self.timers.ack()
        if page is not None:
            self.page_i = page
        self.page.snap(self.page_i)
        self.is_open = True
        self.open_t = time.monotonic()
        self.pw.snap(0)
        self.ph.snap(0)
        self.pp.snap(0)
        self.ca.snap(0)
        THEME.refresh(force=True)
        self.catcher.present()
        self.win.present()
        self._start_frames()

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        self._start_frames()

    def set_page(self, i):
        i = max(0, min(3, i))
        if i != self.page_i:
            self.page_i = i
            self.page.t = float(i)
            self._start_frames()

    def goto_today(self):
        self.set_page(0)
        today = dt.date.today()
        self._set_view(today.year, today.month, 1 if (today.year, today.month) > self.view else -1)
        self.selected = today
        self.tpop.x, self.tpop.v, self.tpop.t = 0.0, 0.0, 1.0

    def _set_view(self, y, m, direction):
        if (y, m) == self.view:
            return
        self.view = (y, m)
        self.slide_dir = direction
        self.slide.x, self.slide.v, self.slide.t = 0.0, 0.0, 1.0
        self._start_frames()

    def shift_month(self, d):
        y, m = self.view
        m += d
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        self._set_view(y, m, d)

    # --------------------------------------------------------------- windows
    def _ensure_windows(self):
        if self.win is not None:
            return
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('clock-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.TOP)
        LS.set_namespace(catcher, 'clock-island-catcher')
        for e in (LS.Edge.TOP, LS.Edge.RIGHT, LS.Edge.BOTTOM, LS.Edge.LEFT):
            LS.set_anchor(catcher, e, True)
        LS.set_exclusive_zone(catcher, -1)
        LS.set_keyboard_mode(catcher, LS.KeyboardMode.NONE)
        blank = Gtk.Box()
        blank.set_hexpand(True)
        blank.set_vexpand(True)
        click = Gtk.GestureClick()
        click.connect('pressed', lambda g, n, x, y: self.close())
        blank.add_controller(click)
        catcher.set_child(blank)
        self.catcher = catcher

        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('clock-island')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'clock-island')
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_keyboard_mode(win, LS.KeyboardMode.ON_DEMAND)
        win.set_default_size(WIN_W, WIN_H)
        da = Gtk.DrawingArea()
        da.set_content_width(WIN_W)
        da.set_content_height(WIN_H)
        da.set_draw_func(self.draw)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_leave)
        da.add_controller(motion)
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect('released', self._on_click)
        da.add_controller(click)
        rclick = Gtk.GestureClick()
        rclick.set_button(3)
        rclick.connect('released', lambda g, n, x, y: self.close())    # right-click anywhere on the island closes it
        da.add_controller(rclick)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self._on_scroll)
        da.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._on_key)
        win.add_controller(keys)
        win.set_child(da)
        css = Gtk.CssProvider()
        css.load_from_string('window.clock-island, window.clock-catcher { background: transparent; }')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win, self.da = win, da

    # ---------------------------------------------------------------- frames
    def _start_frames(self):
        if self.win is not None and self.frame_tick is None:
            self._fl = None
            self.frame_tick = self.da.add_tick_callback(self._frame)

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        busy_prev = getattr(self, '_busy', True)
        gap = .0155 if busy_prev else .033
        if self._fl and now - self._fl < gap:
            return GLib.SOURCE_CONTINUE
        dt_ = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        THEME.refresh()
        self.t += dt_
        o = 1.0 if self.is_open else 0.0
        for sp, (z_open, w_open) in ((self.pw, (.62, 16.0)), (self.ph, (.68, 12.5)), (self.pp, (.7, 15.0))):
            sp.t = o
            sp.z, sp.o = (z_open, w_open) if self.is_open else (.9, w_open * 1.7)
        self.ca.t = 1.0 if (self.is_open and self.ph.x > .55) else 0.0
        busy = False
        for sp in [self.pw, self.ph, self.pp, self.ca, self.slide, self.tpop, self.page] + list(self.press_pop.values()):
            sp.step(dt_)
            busy = busy or not sp.settled
        if self.is_open and self.open_t and time.monotonic() - self.open_t > .35 and self.tpop.t == 0:
            self.tpop.t = 1.0
        self._busy = busy
        self.da.queue_draw()
        self._update_region()
        if not self.is_open and not busy:
            self.win.set_visible(False)
            self.catcher.set_visible(False)
            self.frame_tick = None
            self.region_key = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _rect(self):
        w = lerp(self.cap_w, EW, self.pw.x)
        h = lerp(CAP_H, EH, self.ph.x)
        x = lerp(CAP_X, EX, self.pp.x)
        y = lerp(CAP_Y, EY, self.pp.x)
        return x, y, max(8.0, w), max(8.0, h)

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        if self.is_open:
            x, y, w, h = self._rect()
            key = (int(x), int(y), int(w), int(h))
        else:
            key = None
        if key == self.region_key:
            return
        self.region_key = key
        surface.set_input_region(cairo.Region([cairo.RectangleInt(*key)]) if key else cairo.Region())

    # ------------------------------------------------------------------ draw
    def draw(self, area, cr, W, H):
        # fade in/out over the first quarter of the morph so the real bar clock is revealed (or hidden) smoothly
        fa = clamp(self.pp.x * 4.0)
        if fa < .01:
            return
        if fa < .995:
            cr.push_group()
            self._draw(area, cr, W, H)
            cr.pop_group_to_source()
            cr.paint_with_alpha(fa)
        else:
            self._draw(area, cr, W, H)

    def _draw(self, area, cr, W, H):
        x, y, w, h = self._rect()
        rad = lerp(13.5, 34.0, clamp(self.ph.x))
        sa = clamp(self.ph.x * 1.4)
        if sa > .02:
            cr.save()
            cr.translate(x, y)
            cr.scale(w / EW, h / EH)
            cr.push_group()
            gfx.shadow(cr, 0, 0, EW, EH, 34, 1.5, 10)
            cr.pop_group_to_source()
            cr.paint_with_alpha(sa)
            cr.restore()
        rrect(cr, x, y, w, h, rad)
        cr.set_source_rgb(*BLACK)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, .07)
        cr.set_line_width(1)
        cr.stroke()
        ca = clamp(self.ca.x)
        if ca > .01:
            cr.save()
            rrect(cr, x, y, w, h, rad)
            cr.clip()
            cr.translate(x, y)
            self._content(cr, ca)
            cr.restore()

    def _pointer_local(self):
        if self.pointer is None:
            return None
        x, y, _, _ = self._rect()
        return self.pointer[0] - x, self.pointer[1] - y

    # ---- zones: clickable areas registered while drawing (island-local coordinates)
    def _zone(self, key, shape, *a):
        self.zones.append((key, shape, a))
        p = self.local
        if p is None:
            return False
        return self._inside(shape, a, p)

    @staticmethod
    def _inside(shape, a, p):
        if shape == 'c':
            cx, cy, r = a
            return (p[0] - cx) ** 2 + (p[1] - cy) ** 2 <= r * r
        x, y, w, h = a
        return x <= p[0] <= x + w and y <= p[1] <= y + h

    def _press(self, key):
        sp = self.press_pop.get(key)
        if sp is None:
            sp = self.press_pop[key] = Spring(0, omega=26, zeta=.35)
        sp.x, sp.v, sp.t = -.18, 0.0, 0.0
        self._start_frames()

    def _pop(self, key):
        sp = self.press_pop.get(key)
        return 1.0 + (sp.x if sp else 0.0)

    # --------------------------------------------------------------- content
    def _content(self, cr, ca):
        th = THEME
        txt, acc = th.text, th.accent
        now = dt.datetime.now()
        self.local = self._pointer_local()
        self.zones = []
        cr.translate(0, (1 - ca) * 10)
        cr.push_group()
        self._header(cr, now, txt, acc)
        self._tabs(cr, txt, acc)
        px = self.page.x
        for i in range(4):
            off = i - px
            if abs(off) >= 1:
                continue
            active = abs(i - self.page.t) < .01 and abs(off) < .35
            cr.push_group()
            cr.translate(off * 56, 0)
            keep = self.zones
            if not active:
                self.zones = []
            (self._page_cal, self._page_timer, self._page_pomo, self._page_sw)[i](cr, now, txt, acc)
            if not active:
                self.zones = keep
            cr.pop_group_to_source()
            cr.paint_with_alpha(clamp(1 - abs(off)))
        cr.pop_group_to_source()
        cr.paint_with_alpha(ca)

    def _header(self, cr, now, txt, acc):
        local = self.local
        hour = now.hour + now.minute / 60
        mono = time.monotonic()
        blink = 0.0
        if self.blink_at <= mono < self.blink_at + .16:
            blink = math.sin((mono - self.blink_at) / .16 * math.pi) * .9
        elif mono >= self.blink_at + .16:
            self.blink_at = mono + 2.5 + (hash(int(mono)) % 35) / 10
        bob = math.sin(self.t * 2.0) * 1.6
        look = 0.0
        if local is not None:
            look = max(-1.0, min(1.0, (local[0] - 44) / 160))
        wx = self.wx
        cute.draw_condition(cr, 46, 46 + bob, 21, self.t, wx['cond'] if wx else 'clear', cute.sun_amount(hour), blink, hour, 1.0, look)
        ts = now.strftime('%H:%M')
        lay = gfx.text_layout(ts, 40, True)
        tw, th_ = gfx.text_size(lay)
        dl(cr, lay, 84, 18, (*txt, 1))
        if True:       # the island always shows seconds (the bar clock follows the setting)
            live(cr, now.strftime(':%S'), 20, True, 84 + tw + 2, 18 + th_ - 18, (*txt, .55), left=True)
        wd = '星期' + '一二三四五六日'[now.weekday()]
        dl(cr, gfx.text_layout('%d年%d月%d日 %s · 第%d周' % (now.year, now.month, now.day, wd, now.isocalendar()[1]), 13), 86, 68, (*txt, .62))
        greet = '夜深了' if now.hour < 5 else '早上好' if now.hour < 11 else '中午好' if now.hour < 13 else '下午好' if now.hour < 18 else '晚上好'
        gl = gfx.text_layout(greet, 13, True)
        dl(cr, gl, EW - 22 - gfx.text_size(gl)[0], 26, (*acc, .95))
        info = ('%s · %d°C' % (wx['name'], round(wx['temp']))) if wx else '第 %d 周' % now.isocalendar()[1]
        wk = gfx.text_layout(info, 12)
        dl(cr, wk, EW - 22 - gfx.text_size(wk)[0], 48, (*txt, .6))

    def _tabs(self, cr, txt, acc):
        x0, y0, w, h = 16.0, 96.0, EW - 32, 32.0
        rrect(cr, x0, y0, w, h, 16)
        cr.set_source_rgba(*txt, .07)
        cr.fill()
        cw = w / 4
        px = clamp(self.page.x, -.3, 3.3)
        rrect(cr, x0 + 3 + cw * px, y0 + 3, cw - 6, h - 6, 13)
        cr.set_source_rgba(*acc, .3)
        cr.fill()
        tm, pm, sw = self.timers.tm_running(), self.timers.pm_running(), self.timers.sw_running()
        running = (False, tm, pm, sw)
        for i, name in enumerate(PAGES):
            cx = x0 + cw * (i + .5)
            hot = self._zone('tab:%d' % i, 'r', x0 + cw * i, y0, cw, h)
            act = 1 - clamp(abs(i - self.page.x))
            ctext(cr, name, 13, True, cx, y0 + h / 2, (*txt, .5 + .45 * act + (.1 if hot else 0)))
            if running[i]:
                pulse = .6 + .4 * math.sin(self.t * 5)
                cr.arc(cx + 24 + (4 if len(name) > 2 else 0), y0 + 9, 2.8, 0, math.tau)
                cr.set_source_rgba(*(PHASE_COL['focus'] if i == 2 else acc if i == 1 else SW_COL), pulse)
                cr.fill()

    # ------------------------------------------------------------- calendar
    def _page_cal(self, cr, now, txt, acc):
        th = THEME
        local = self.local
        y, m = self.view
        sl = clamp(self.slide.x)
        off = (1 - sl) * self.slide_dir * 34
        title = gfx.text_layout('%d年%d月' % (y, m), 18, True)
        cr.push_group()
        dl(cr, title, 22 + off, 142, (*txt, 1))
        cr.pop_group_to_source()
        cr.paint_with_alpha(clamp(sl * 1.2))
        pv, nx = (EW - 76, 156.0), (EW - 36, 156.0)
        for key, (bx, by) in (('cal:prev', pv), ('cal:next', nx)):
            hot = self._zone(key, 'c', bx, by, 17)
            cr.arc(bx, by, 15, 0, math.tau)
            cr.set_source_rgba(*txt, .16 if hot else .07)
            cr.fill()
            cr.set_source_rgba(*txt, .9)
            cr.set_line_width(1.8)
            cr.set_line_cap(1)
            cr.set_line_join(1)
            d = -1 if key == 'cal:prev' else 1
            cr.move_to(bx - d * 2.5, by - 5)
            cr.line_to(bx + d * 2.5, by)
            cr.line_to(bx - d * 2.5, by + 5)
            cr.stroke()
        tdy = (EW - 172, 142.0, 62.0, 28.0)
        hot = self._zone('cal:today', 'r', *tdy)
        rrect(cr, *tdy, 14)
        cr.set_source_rgba(*acc, .34 if hot else .2)
        cr.fill()
        ctext(cr, '今天', 13, True, tdy[0] + tdy[2] / 2, tdy[1] + tdy[3] / 2, (*acc, 1))
        cw = (EW - 2 * GRID_X) / COLS
        for i, ch in enumerate(WEEK):
            ctext(cr, ch, 12.5, True, GRID_X + cw * (i + .5), 188, (*(th.danger if i >= 5 else txt), .5 if i < 5 else .62))
        first = dt.date(y, m, 1)
        start = first - dt.timedelta(days=first.weekday())
        today = dt.date.today()
        since = time.monotonic() - self.open_t
        cr.push_group()
        hov_idx = None
        for idx in range(42):
            d = start + dt.timedelta(days=idx)
            r, c = divmod(idx, COLS)
            cx = GRID_X + cw * (c + .5) + off
            cy = GRID_Y + ROW_H * (r + .5)
            hov = self._zone('cell:%d' % idx, 'c', cx - off, cy, 17)
            rev = ease_back((since - .14 - idx * .007) / .3)
            if rev <= .01:
                continue
            inmonth = d.month == m
            cr.save()
            cr.translate(cx, cy)
            cr.scale(max(.01, rev), max(.01, rev))
            alpha = (1.0 if inmonth else .28)
            if d == today:
                p = max(0.0, self.tpop.x)
                cr.arc(0, 0, 16 * min(1.25, p), 0, math.tau)
                cr.set_source_rgba(*acc, 1)
                cr.fill()
                col = (1, 1, 1, 1)
            else:
                if hov:
                    cr.arc(0, 0, 16, 0, math.tau)
                    cr.set_source_rgba(*txt, .13)
                    cr.fill()
                if d == self.selected:
                    cr.arc(0, 0, 15.2, 0, math.tau)
                    cr.set_source_rgba(*acc, .9)
                    cr.set_line_width(1.6)
                    cr.stroke()
                col = (*(th.danger if c >= 5 else txt), alpha * (.9 if c >= 5 else .92))
            mask_text(cr, str(d.day), 15, d == today or hov, 0, 0, col)
            cr.restore()
        cr.pop_group_to_source()
        cr.paint_with_alpha(clamp(sl * 1.3))
        days = 366 if calendar.isleap(now.year) else 365
        doy = now.timetuple().tm_yday - 1 + (now.hour * 3600 + now.minute * 60 + now.second) / 86400
        frac = clamp(doy / days)
        prog = clamp((since - .3) / .9)
        bar = ease_back(prog) * frac
        fx, fy, fw = 22.0, EH - 28, EW - 44
        dl(cr, gfx.text_layout('今年已过 %d%%' % round(frac * 100), 12), fx, fy - 20, (*txt, .55))
        rest = gfx.text_layout('还剩 %d 天' % (days - int(doy) - 1), 12)
        dl(cr, rest, fx + fw - gfx.text_size(rest)[0], fy - 20, (*txt, .55))
        rrect(cr, fx, fy, fw, 6, 3)
        cr.set_source_rgba(*txt, .1)
        cr.fill()
        g = cairo.LinearGradient(fx, 0, fx + fw, 0)
        g.add_color_stop_rgb(0, 1.0, .72, .3)
        g.add_color_stop_rgb(1, *acc)
        rrect(cr, fx, fy, max(6.0, fw * bar), 6, 3)
        cr.set_source(g)
        cr.fill()

    # ----------------------------------------------------------- shared bits
    def _ring(self, cr, frac, col, col2=None, width=10.0, alpha=1.0, glow=0.0):
        cx, cy = RING_C
        cr.set_line_width(width)
        cr.set_line_cap(1)
        cr.new_path()
        cr.arc(cx, cy, RING_R, 0, math.tau)
        cr.set_source_rgba(*THEME.text, .09)
        cr.stroke()
        frac = clamp(frac)
        if frac > .002:
            g = cairo.LinearGradient(cx - RING_R, cy - RING_R, cx + RING_R, cy + RING_R)
            g.add_color_stop_rgba(0, *col, alpha)
            g.add_color_stop_rgba(1, *(col2 or col), alpha)
            if glow > 0:
                cr.set_line_width(width + 8)
                cr.set_source_rgba(*col, glow * .18)
                cr.arc(cx, cy, RING_R, -math.pi / 2, -math.pi / 2 + math.tau * frac)
                cr.stroke()
                cr.set_line_width(width)
            cr.set_source(g)
            cr.arc(cx, cy, RING_R, -math.pi / 2, -math.pi / 2 + math.tau * frac)
            cr.stroke()
            # a bright dot rides the tip
            a = -math.pi / 2 + math.tau * frac
            cr.arc(cx + math.cos(a) * RING_R, cy + math.sin(a) * RING_R, width * .28, 0, math.tau)
            cr.set_source_rgba(1, 1, 1, .85 * alpha)
            cr.fill()

    def _round_btn(self, cr, key, cx, cy, r, icon, fg, bg, bg_alpha=.1, hot_alpha=.2, isize=None):
        hot = self._zone(key, 'c', cx, cy, r + 3)
        s = self._pop(key)
        cr.save()
        cr.translate(cx, cy)
        cr.scale(s, s)
        cr.arc(0, 0, r, 0, math.tau)
        cr.set_source_rgba(*bg, hot_alpha if hot else bg_alpha)
        cr.fill()
        icon(cr, 0, 0, isize or r * .8, (*fg, 1))
        cr.restore()

    def _main_btn(self, cr, key, cx, cy, col, running):
        hot = self._zone(key, 'c', cx, cy, 33)
        s = self._pop(key) * (1.04 if hot else 1.0)
        cr.save()
        cr.translate(cx, cy)
        cr.scale(s, s)
        g = cairo.LinearGradient(0, -28, 0, 28)
        g.add_color_stop_rgb(0, *[min(1, v + .12) for v in col])
        g.add_color_stop_rgb(1, *[v * .85 for v in col])
        cr.arc(0, 0, 28, 0, math.tau)
        cr.set_source(g)
        cr.fill()
        (icon_pause if running else icon_play)(cr, 0, 0, 22, (1, 1, 1, 1))
        cr.restore()

    def _chip(self, cr, key, x, y, w, h, label, active, col, txt):
        hot = self._zone(key, 'r', x, y, w, h)
        rrect(cr, x, y, w, h, h / 2)
        if active:
            cr.set_source_rgba(*col, .3)
        else:
            cr.set_source_rgba(*txt, .13 if hot else .07)
        cr.fill()
        ctext(cr, label, 12.5, True, x + w / 2, y + h / 2, (*(col if active else txt), 1.0 if active else .75))

    # ---------------------------------------------------------------- timer
    def _page_timer(self, cr, now, txt, acc):
        tm = self.timers
        t = tm.tm
        left = tm.tm_left()
        running = tm.tm_running()
        dur = max(1, t['dur'])
        done = t['done']
        cx, cy = RING_C
        frac = (left / dur) if (running or left < dur) and not done else 1.0
        pulse = (.5 + .5 * math.sin(self.t * 6)) if done else 0.0
        col = (1.0, .4, .4) if done else acc
        self._ring(cr, 1.0 if done else frac, col, (.45, .85, 1.0) if not done else (1, .65, .4), glow=(.4 + pulse) if (running or done) else 0.0)
        live(cr, T.fmt_clock(left), 38, True, cx, cy - 6, (*txt, 1))
        sub = '时间到' if done else ('倒计时中' if running else '已设定 ' + T.fmt_dur(dur))
        ctext(cr, sub, 12.5, False, cx, cy + 32, (*(col if done else txt), .8 if done else .55))
        # +/- one minute when idle
        for key, bx, minus in (('tm:minus', 34.0, True), ('tm:plus', EW - 34.0, False)):
            if not running:
                self._round_btn(cr, key, bx, cy, 15, lambda c, x, y, s, col, m=minus: icon_plus(c, x, y, s, col, m), txt, txt, .07, .16, 15)
        # presets
        presets = (60, 180, 300, 600, 900, 1800)
        labels = ('1分', '3分', '5分', '10分', '15分', '30分')
        cw = (EW - 32) / 6
        for i, (sec, lab) in enumerate(zip(presets, labels)):
            self._chip(cr, 'tm:preset:%d' % sec, 16 + cw * i + 2, 372, cw - 4, 28, lab, int(t['dur']) == sec, acc, txt)
        by = 440
        self._round_btn(cr, 'tm:reset', EW / 2 - 70, by, 21, icon_reset, txt, txt)
        self._main_btn(cr, 'tm:toggle', EW / 2, by, col if not done else acc, running)
        if running:
            self._chip(cr, 'tm:extend', EW / 2 + 49, by - 14, 44, 28, '+1分', False, acc, txt)

    # ------------------------------------------------------------- pomodoro
    def _page_pomo(self, cr, now, txt, acc):
        tm = self.timers
        p = tm.pm
        phase = p['phase']
        col = PHASE_COL[phase]
        left = tm.pm_left()
        total = max(1.0, tm.pm_total())
        running = tm.pm_running()
        cx, cy = RING_C
        frac = left / total
        self._ring(cr, frac, col, tuple(min(1, v + .22) for v in col), glow=.7 if running else 0.0)
        mono = time.monotonic()
        blink = 0.0
        if self.blink_at <= mono < self.blink_at + .16:
            blink = math.sin((mono - self.blink_at) / .16 * math.pi) * .9
        mood = 'focus' if (phase == 'focus' and running) else 'rest' if phase != 'focus' else 'idle'
        hop = abs(math.sin(self.t * 4)) * 3 if (running and phase != 'focus') else 0.0
        cute.draw_tomato(cr, cx, cy - 32 - hop, 25, self.t, mood, blink, 1.0, col if phase == 'focus' else col)
        live(cr, T.fmt_clock(left), 34, True, cx, cy + 22, (*txt, 1))
        ctext(cr, '%s%s' % (T.PHASE_NAME[phase], '' if running else ' · 已暂停' if left < total - 1 else ''), 12.5, True, cx, cy + 50, (*col, .95))
        # four dots = progress through the current set of four
        done_n = p['cycle'] % 4
        for i in range(4):
            dx = cx + (i - 1.5) * 18
            filled = i < done_n or (phase != 'focus' and i == done_n - 1 and False)
            cr.new_path()
            cr.arc(dx, 362, 4.2, 0, math.tau)
            if filled:
                cr.set_source_rgba(*PHASE_COL['focus'], 1)
                cr.fill()
            else:
                cr.set_source_rgba(*txt, .25)
                cr.set_line_width(1.4)
                cr.stroke()
        cw = (EW - 32 - 16) / 3
        for i, ph in enumerate(T.PHASES):
            self._chip(cr, 'pm:phase:' + ph, 16 + (cw + 8) * i, 378, cw, 28, T.PHASE_NAME[ph], ph == phase, PHASE_COL[ph], txt)
        by = 444
        self._round_btn(cr, 'pm:reset', EW / 2 - 70, by, 21, icon_reset, txt, txt)
        self._main_btn(cr, 'pm:toggle', EW / 2, by, col, running)
        self._round_btn(cr, 'pm:skip', EW / 2 + 70, by, 21, icon_skip, txt, txt)
        n = p['today']
        ctext(cr, '今天已完成 %d 个番茄' % n, 12, False, EW - 96, 142, (*txt, .5)) if False else None
        lab = gfx.text_layout('今天 %d 个番茄' % n, 12)
        dl(cr, lab, EW - 22 - gfx.text_size(lab)[0], 142, (*txt, .55))

    # ------------------------------------------------------------ stopwatch
    def _page_sw(self, cr, now, txt, acc):
        tm = self.timers
        el = tm.sw_elapsed()
        running = tm.sw_running()
        cx, cy = RING_C
        # dial: 60 ticks, a sweeping dot, the current minute drawn as an arc
        for i in range(60):
            a = -math.pi / 2 + i * math.tau / 60
            big = i % 5 == 0
            r0, r1 = RING_R + 8, RING_R + (15 if big else 11)
            cr.set_source_rgba(*txt, .5 if big else .2)
            cr.set_line_width(1.8 if big else 1.0)
            cr.move_to(cx + math.cos(a) * r0, cy + math.sin(a) * r0)
            cr.line_to(cx + math.cos(a) * r1, cy + math.sin(a) * r1)
            cr.stroke()
        sec_frac = (el % 60.0) / 60.0
        self._ring(cr, sec_frac if el > 0 else 0.0, SW_COL, (1.0, .5, .4), glow=.7 if running else 0.0)
        mm, ss = divmod(el, 60.0)
        hh, mm = divmod(int(mm), 60)
        txt_main = ('%d:%02d:%02d' % (hh, mm, int(ss))) if hh else ('%02d:%02d' % (mm, int(ss)))
        live(cr, txt_main, 36, True, cx, cy - 8, (*txt, 1))
        live(cr, '.%02d' % int((el * 100) % 100), 18, True, cx, cy + 26, (*SW_COL, .95))
        # laps (newest first)
        laps = tm.sw['laps']
        if laps:
            for j, i in enumerate(range(len(laps) - 1, max(-1, len(laps) - 3), -1)):
                prev = laps[i - 1] if i > 0 else 0.0
                y = 372 + j * 24
                dl(cr, gfx.text_layout('第 %d 圈' % (i + 1), 12), 26, y, (*txt, .55))
                live(cr, T.fmt_clock(0) if False else '+%s' % _fmt_cs(laps[i] - prev), 13, True, EW / 2, y + 8, (*txt, .95))
                lay = gfx.text_layout(_fmt_cs(laps[i]), 12)
                gfx.draw_layout(cr, lay, EW - 26 - gfx.text_size(lay)[0], y, (*txt, .55))
        else:
            ctext(cr, '点右侧的旗子记录一圈' if running else '点开始，开始计时', 12.5, False, EW / 2, 384, (*txt, .4))
        by = 444
        self._round_btn(cr, 'sw:reset', EW / 2 - 70, by, 21, icon_reset, txt, txt)
        self._main_btn(cr, 'sw:toggle', EW / 2, by, SW_COL, running)
        self._round_btn(cr, 'sw:lap', EW / 2 + 70, by, 21, icon_flag, txt if running else (*[v * .5 for v in txt],), txt)

    # ------------------------------------------------------------- hit tests
    def _cell_date(self, idx):
        y, m = self.view
        first = dt.date(y, m, 1)
        return first - dt.timedelta(days=first.weekday()) + dt.timedelta(days=idx)

    # ----------------------------------------------------------------- input
    def _on_motion(self, ctl, x, y):
        self.pointer = (x, y)
        self._start_frames()

    def _on_leave(self, ctl):
        self.pointer = None
        self._start_frames()

    def _on_click(self, gesture, n, x, y):
        if not self.is_open:
            return
        bx, by, _, _ = self._rect()
        p = (x - bx, y - by)
        for key, shape, a in reversed(self.zones):
            if self._inside(shape, a, p):
                self._act(key)
                break
        self._start_frames()

    def _act(self, key):
        tm = self.timers
        parts = key.split(':')
        kind = parts[0]
        if kind != 'cell':
            self._press(key)
        if kind == 'tab':
            self.set_page(int(parts[1]))
        elif kind == 'cal':
            if parts[1] == 'prev':
                self.shift_month(-1)
            elif parts[1] == 'next':
                self.shift_month(1)
            else:
                self.goto_today()
        elif kind == 'cell':
            d = self._cell_date(int(parts[1]))
            self.selected = d
            if d.month != self.view[1]:
                self._set_view(d.year, d.month, 1 if d > dt.date(*self.view, 1) else -1)
            if d == dt.date.today():
                self.tpop.x, self.tpop.v, self.tpop.t = 0.0, 0.0, 1.0
        elif kind == 'tm':
            if parts[1] == 'toggle':
                tm.tm_toggle()
            elif parts[1] == 'reset':
                tm.tm_reset()
            elif parts[1] == 'plus':
                tm.tm_adjust(60)
            elif parts[1] == 'minus':
                tm.tm_adjust(-60)
            elif parts[1] == 'extend':
                t = tm.tm
                if t['end']:
                    t['end'] += 60
                    t['dur'] += 60
                    tm.save()
            elif parts[1] == 'preset':
                tm.tm_set(int(parts[2]))
        elif kind == 'pm':
            if parts[1] == 'toggle':
                tm.pm_toggle()
            elif parts[1] == 'reset':
                tm.pm_reset()
            elif parts[1] == 'skip':
                tm.pm_skip()
            elif parts[1] == 'phase':
                tm.pm_pick(parts[2])
        elif kind == 'sw':
            if parts[1] == 'toggle':
                tm.sw_toggle()
            elif parts[1] == 'reset':
                tm.sw_reset()
            elif parts[1] == 'lap':
                tm.sw_lap()

    def _on_scroll(self, ctl, dx, dy):
        if not self.is_open or abs(dy) < .01:
            return True
        if self.page_i == 0:
            self.shift_month(1 if dy > 0 else -1)
        elif self.page_i == 1:
            self.timers.tm_adjust(-60 if dy > 0 else 60)
            self._start_frames()
        return True

    def _on_key(self, ctl, keyval, keycode, state):
        name = Gdk.keyval_name(keyval)
        pg = self.page_i
        if name == 'Escape':
            self.close()
        elif name in ('1', '2', '3', '4'):
            self.set_page(int(name) - 1)
        elif name == 'Tab':
            self.set_page((pg + 1) % 4)
        elif name in ('Left', 'Page_Up'):
            self.shift_month(-1) if pg == 0 else self.set_page(pg - 1)
        elif name in ('Right', 'Page_Down'):
            self.shift_month(1) if pg == 0 else self.set_page(pg + 1)
        elif name in ('Home', 't', 'T'):
            self.goto_today()
        elif name == 'space' and pg > 0:
            self._act(('', 'tm:toggle', 'pm:toggle', 'sw:toggle')[pg])
        elif name in ('r', 'R') and pg > 0:
            self._act(('', 'tm:reset', 'pm:reset', 'sw:reset')[pg])
        elif name in ('l', 'L') and pg == 3:
            self._act('sw:lap')
        elif name in ('n', 'N') and pg == 2:
            self._act('pm:skip')
        else:
            return False
        self._start_frames()
        return True


def _fmt_cs(secs):
    secs = max(0.0, secs)
    m, s = divmod(secs, 60.0)
    return '%02d:%05.2f' % (int(m), s)


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    lock = open(STATE / 'island.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    app = Gtk.Application(application_id='dev.pr.ClockIsland', flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def on_activate(a):
        a.hold()
        holder['island'] = Island(a)

    app.connect('activate', on_activate)
    app.run([])


if __name__ == '__main__':
    main()

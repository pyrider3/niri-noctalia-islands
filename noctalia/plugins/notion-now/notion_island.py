#!/usr/bin/env python3
"""Notion Now island: the bar's agenda capsule morphs into a black dynamic island.

Shows the current / next event, a day timeline, the agenda list and the quick alarm; reminders (event about to
start, event started, alarm ringing) pop the island open as a small banner. Commands arrive via
~/.local/state/notion-now/island-cmd.json (written by widget.luau).

Shares the text/spring helpers of the clock island (~/.config/noctalia/plugins/clock-island) and of notifd.
"""
import datetime as dt
import fcntl
import io
import json
import math
import os
import subprocess
import sys
import threading
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
sys.path.insert(0, str(HERE.parent / 'clock-island'))
sys.path.insert(0, str(Path.home() / '.config/notifd'))

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

import barpos  # noqa: E402
import gfx  # noqa: E402
from alarm_store import AlarmStore  # noqa: E402
from clock_island import dl, ease_back, mask_text, live, ctext, icon_pause, icon_play, icon_plus, icon_reset  # noqa: E402
from gfx import THEME, Spring, clamp, lerp, rrect  # noqa: E402

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'notion-now'
EVENTS_FILE = Path(os.environ.get('NN_EVENTS', str(STATE / 'events.json')))
BLACK = (.012, .012, .018)
CAP_H = 26.0
CAP_Y = 7.0
EW, EH = 420.0, 560.0
BW, BH = 400.0, 134.0
WIN_W, WIN_H = 520, 600
BANNER_SECONDS = 9.0
LEAD_MIN = 5
SOUND = '/usr/share/sounds/freedesktop/stereo/message-new-instant.oga'
ALARM_CHIPS = ((5, '5分'), (10, '10分'), (15, '15分'), (30, '30分'), (60, '1小时'))
WEEKDAY = '一二三四五六日'

# approximate bar geometry (layout px), derived from the neighbouring widgets' widths
CLOCK_STATUS = Path.home() / '.local/state/clock-island/status.json'


def read_json(p):
    try:
        v = json.loads(Path(p).read_text())
        return v if isinstance(v, (dict, list)) else {}
    except (OSError, ValueError):
        return {}


def hm(ts):
    return time.strftime('%H:%M', time.localtime(ts))


def fmt_left(secs):
    secs = int(max(0, secs))
    if secs >= 3600:
        h, m = divmod(secs // 60, 60)
        return '%d 小时 %d 分' % (h, m) if m else '%d 小时' % h
    if secs >= 60:
        return '%d 分钟' % (secs // 60 + (1 if secs % 60 else 0))
    return '%d 秒' % secs


MARK_TO_CAPSULE = 6.0                        # capsule left edge = calendar icon body left - (inset .5 + padding 5.5)


def screen_info():
    return barpos.screen_info()


def find_marker():
    st = read_json(STATE / 'bar-status.json')
    mk = st.get('marker') if isinstance(st, dict) else None
    if not mk:
        return None
    r = barpos.find_marker(tuple(int(v) for v in mk), min_run=3)
    return None if r is None else r[0] - MARK_TO_CAPSULE


def spawn(cmd):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threading.Thread(target=p.wait, daemon=True).start()
    except OSError:
        pass


def play(path=SOUND):
    if os.path.exists(path):
        spawn(['paplay', '--client-name=notion-now-sound', path])


# ------------------------------------------------------------------- icons
def draw_calendar(cr, cx, cy, s, day, t, wiggle=0.0, accent=(1.0, .42, .38)):
    cr.save()
    cr.translate(cx, cy)
    cr.rotate(math.sin(t * 18) * .22 * wiggle)
    w = s * 1.5
    h = s * 1.5
    rrect(cr, -w / 2, -h / 2, w, h, s * .3)
    cr.set_source_rgb(.97, .97, .99)
    cr.fill()
    cr.save()
    rrect(cr, -w / 2, -h / 2, w, h, s * .3)
    cr.clip()
    cr.rectangle(-w / 2, -h / 2, w, h * .32)
    cr.set_source_rgb(*accent)
    cr.fill()
    cr.restore()
    cr.set_source_rgb(.85, .85, .9)
    for sx in (-1, 1):
        rrect(cr, sx * w * .24 - s * .07, -h / 2 - s * .12, s * .14, s * .3, s * .07)
        cr.fill()
    ctext(cr, str(day), s * .95, True, 0, h * .12, (.15, .15, .2, 1))
    cr.restore()


def draw_bell(cr, cx, cy, s, t, ring=0.0, col=(1, 1, 1)):
    cr.save()
    cr.translate(cx, cy - s * .4)
    cr.rotate(math.sin(t * 22) * .38 * ring)
    cr.translate(0, s * .4)
    cr.set_source_rgba(*col, 1)
    cr.move_to(-s * .5, s * .38)
    cr.curve_to(-s * .36, s * .28, -s * .3, s * .08, -s * .3, -s * .12)
    cr.curve_to(-s * .3, -s * .38, -s * .15, -s * .5, 0, -s * .5)
    cr.curve_to(s * .15, -s * .5, s * .3, -s * .38, s * .3, -s * .12)
    cr.curve_to(s * .3, s * .08, s * .36, s * .28, s * .5, s * .38)
    cr.close_path()
    cr.fill()
    cr.arc(0, -s * .58, s * .07, 0, math.tau)
    cr.fill()
    cr.arc(-math.sin(t * 22) * ring * s * .22, s * .5, s * .11, 0, math.tau)
    cr.fill()
    cr.restore()


def icon_back(cr, cx, cy, s, col):
    cr.set_source_rgba(*col)
    cr.set_line_width(max(1.8, s * .2))
    cr.set_line_cap(1)
    cr.set_line_join(1)
    cr.move_to(cx + s * .2, cy - s * .42)
    cr.line_to(cx - s * .22, cy)
    cr.line_to(cx + s * .2, cy + s * .42)
    cr.stroke()


def draw_gear(cr, cx, cy, s, col):
    cr.save()
    cr.translate(cx, cy)
    cr.set_source_rgba(*col)
    cr.set_line_width(max(1.5, s * .16))
    cr.set_line_cap(1)
    cr.arc(0, 0, s * .26, 0, math.tau)
    cr.stroke()
    for i in range(8):
        a = i * math.tau / 8
        cr.move_to(math.cos(a) * s * .38, math.sin(a) * s * .38)
        cr.line_to(math.cos(a) * s * .52, math.sin(a) * s * .52)
        cr.stroke()
    cr.restore()


def draw_cup(cr, cx, cy, s, t, sad=False):
    """Sleepy coffee cup with rising steam (empty state)."""
    cr.save()
    cr.translate(cx, cy)
    # steam
    cr.set_line_width(max(1.4, s * .06))
    cr.set_line_cap(1)
    for i, dx in enumerate((-.22, 0.0, .22)):
        ph = (t * .5 + i * .33) % 1.0
        a = math.sin(ph * math.pi)
        cr.set_source_rgba(1, 1, 1, .35 * a)
        x0 = dx * s
        y0 = -s * .45 - ph * s * .5
        cr.move_to(x0, y0 + s * .3)
        cr.curve_to(x0 + s * .1, y0 + s * .15, x0 - s * .1, y0, x0 + math.sin(t + i) * s * .06, y0 - s * .15)
        cr.stroke()
    # saucer + cup
    cr.set_source_rgb(.82, .84, .9)
    rrect(cr, -s * .62, s * .5, s * 1.24, s * .1, s * .05)
    cr.fill()
    cr.set_source_rgb(.97, .97, 1.0)
    cr.move_to(-s * .5, -s * .3)
    cr.line_to(s * .5, -s * .3)
    cr.curve_to(s * .5, s * .3, s * .3, s * .52, 0, s * .52)
    cr.curve_to(-s * .3, s * .52, -s * .5, s * .3, -s * .5, -s * .3)
    cr.close_path()
    cr.fill()
    cr.set_source_rgb(.97, .97, 1.0)
    cr.set_line_width(s * .13)
    cr.arc(s * .55, s * .02, s * .2, -math.pi * .5, math.pi * .5)
    cr.stroke()
    cr.set_source_rgb(.6, .4, .28)
    rrect(cr, -s * .45, -s * .3, s * .9, s * .1, s * .05)
    cr.fill()
    # face
    cr.set_source_rgba(.3, .22, .2, 1)
    cr.set_line_width(max(1.2, s * .06))
    for sx in (-1, 1):
        cr.arc(sx * s * .2, s * .12, s * .09, math.pi * .1, math.pi * .9)
        cr.stroke()
    cr.arc(0, s * .2, s * .09, math.pi * .15, math.pi * .85)
    cr.stroke()
    cr.set_source_rgba(1, .6, .65, .5)
    for sx in (-1, 1):
        cr.arc(sx * s * .34, s * .24, s * .06, 0, math.tau)
        cr.fill()
    cr.restore()


class Event:
    def __init__(self, d):
        self.d = d
        self.id = d.get('id', '')
        self.title = d.get('title') or '未命名活动'
        self.start = float(d.get('start', 0))
        self.end = float(d.get('end', self.start) or self.start)
        self.all_day = bool(d.get('all_day'))
        self.point = bool(d.get('point'))
        self.url = d.get('url', '')
        self.cal = d.get('calendar', '')
        self.col = gfx.avatar_colour(self.cal or self.title)


class Banner:
    def __init__(self, kind, title, sub, event=None, alarm=None):
        self.kind, self.title, self.sub = kind, title, sub
        self.event, self.alarm = event, alarm
        self.born = time.monotonic()
        self.left = BANNER_SECONDS


class NotionIsland:
    def __init__(self, app):
        self.app = app
        self.win = self.catcher = None
        self.is_open = False
        self.mode = 'panel'            # 'panel' | 'banner'
        self.banner = None
        self.queue = []
        self.alarm_store = AlarmStore()
        self.events = []
        self.day_events = []
        self.all_day = []
        self.sync = {}
        self.events_mt = None
        self.cap_x, self.cap_w = 194.0, 97.0
        self.marker_cap = None          # measured capsule left edge (None = use the estimate)
        self.marker_t = 0.0
        self.locating = False
        self.L = 0.0                    # window left margin (screen x of the window's left edge)
        _, self.screen_w, _ = screen_info()
        self.sx, self.sy = Spring(194, omega=15, zeta=.7), Spring(CAP_Y, omega=15, zeta=.7)
        self.sw, self.sh = Spring(97, omega=16, zeta=.62), Spring(CAP_H, omega=12.5, zeta=.68)
        self.ca = Spring(0, omega=18, zeta=1.0)
        self.t = 0.0
        self.open_t = 0.0
        self.pointer = None
        self.zones = []
        self.local = None
        self.press_pop = {}
        self.tl_scroll = Spring(0, omega=14, zeta=.9)
        self.tl_target = None
        self.page_a = Spring(0, omega=17, zeta=.85)
        self.page = 'main'
        self.stab = 'bar'
        self.tog = {}
        self._prefs = dict(self.PREF_DEFAULTS)
        self._prefs_t = 0.0
        self.saved_at = -10.0
        self.hover_event = None
        self.sync_spin = 0.0
        self.sync_until = 0.0
        self.frame_tick = None
        self._fl = None
        self._busy = True
        self.region_key = None
        self.alarm_seen = None
        self.fired = set(read_json(STATE / 'island-fired.json').get('ids', [])) if isinstance(read_json(STATE / 'island-fired.json'), dict) else set()
        cmd = read_json(STATE / 'island-cmd.json')
        self.cmd_seq = cmd.get('seq') if isinstance(cmd, dict) else None
        self.load_events(force=True)
        self._hovered_before = False
        GLib.timeout_add(100, self._hover_watch)
        GLib.timeout_add(2500, self.locate)
        GLib.timeout_add(1500, self._prewarm)
        GLib.timeout_add(50, self._poll)
        GLib.timeout_add(1000, self._beat)
        GLib.timeout_add(5000, self._reminders)
        GLib.timeout_add(700, self._alarm_watch)
        self._beat()

    # ----------------------------------------------------------------- data
    def load_events(self, force=False):
        try:
            mt = EVENTS_FILE.stat().st_mtime_ns
        except OSError:
            mt = None
        if not force and mt == self.events_mt:
            return
        self.events_mt = mt
        d = read_json(EVENTS_FILE)
        if not isinstance(d, dict):
            d = {}
        self.sync = (d.get('sources') or {}).get('notion') or {}
        self.sync_updated = d.get('updated', 0)
        if self.sync_updated > getattr(self, 'sync_base', 0):      # a manual sync finished: stop the spinner
            self.sync_base = self.sync_updated
            self.sync_until = 0.0
        events = []
        for e in d.get('events') or []:
            try:
                events.append(Event(e))
            except (TypeError, ValueError):
                pass
        events.sort(key=lambda e: (e.start, e.id))
        self.events = events
        self._split()

    def _split(self):
        now = time.time()
        lt = time.localtime(now)
        day0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        day1 = day0 + 86400
        self.day_start = day0
        self.all_day = [e for e in self.events if e.all_day and e.start < day1 and e.end > day0]
        self.day_events = [e for e in self.events if not e.all_day and e.start < day1 and (e.end > day0 or e.start >= day0)]

    # -------------------------------------------------------------- commands
    def _beat(self):
        try:
            tmp = STATE / 'island-alive.tmp'
            tmp.write_text(json.dumps(dict(t=time.time(), open=self.is_open)))
            os.replace(tmp, STATE / 'island-alive.json')
        except OSError:
            pass
        return True

    def _poll(self):
        try:
            d = json.loads((STATE / 'island-cmd.json').read_text())
        except (OSError, ValueError):
            return True
        seq = d.get('seq')
        if seq is None or seq == self.cmd_seq:
            return True
        self.cmd_seq = seq
        cmd = d.get('cmd')
        if cmd == 'toggle':
            if self.is_open and self.mode == 'panel':
                self.close()
            else:
                self.open_panel()
        elif cmd == 'open':
            self.open_panel()
        elif cmd == 'close':
            self.close()
        elif cmd in ('settings', 'settings-remind', 'settings-conn'):
            self.open_panel()
            self.page = 'settings'
            self.stab = {'settings': 'bar', 'settings-remind': 'remind', 'settings-conn': 'conn'}[cmd]
        elif cmd == 'test-banner':
            self.push_banner(Banner('lead', '设计评审', '5 分钟后开始 · %s' % hm(time.time() + 300)))
        return True

    def _prewarm(self):
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

    def locate(self):
        """Measure where the capsule really is (in a thread: a screenshot takes ~100 ms)."""
        if self.locating:
            return
        self.locating = True

        def work():
            x = find_marker()
            GLib.idle_add(self._located, x)
        threading.Thread(target=work, daemon=True).start()

    def _located(self, x):
        self.locating = False
        self.marker_t = time.monotonic()
        if x is not None:
            self.marker_cap = x
            self._measure_capsule()
            if self.is_open:
                self._start_frames()
        return False

    def _hover_watch(self):
        v = read_json(STATE / 'bar-input.json')
        hov = bool(v.get('hovered')) if isinstance(v, dict) else False
        if hov and not self._hovered_before and time.monotonic() - self.marker_t > 1.5:
            self.locate()
        self._hovered_before = hov
        return True

    # ---------------------------------------------------------------- geometry
    def _measure_capsule(self):
        """Where the bar's agenda capsule is: left neighbours are the clock capsule and the small bar button."""
        clock_w = float(read_json(CLOCK_STATUS).get('width', 70) if isinstance(read_json(CLOCK_STATUS), dict) else 70)
        self.cap_x = 24.0 + clock_w + 13.0 + 9.0 + 24.0 + 7.0       # estimate from the left neighbours
        if self.marker_cap is not None and time.monotonic() - self.marker_t < 600:
            self.cap_x = self.marker_cap
        st = read_json(STATE / 'bar-status.json')
        w = float(st.get('width', 64)) if isinstance(st, dict) else 64.0
        self.cap_w = w + 11

    def _target_rect(self):
        if not self.is_open:
            return self.cap_x, CAP_Y, self.cap_w, CAP_H
        if self.mode == 'banner':
            return max(10.0, min(self.screen_w - BW - 10, self.cap_x - 8)), 4.0, BW, BH
        return max(10.0, min(self.screen_w - EW - 10, self.cap_x - 14)), 4.0, EW, EH

    def _final_size(self):
        return (BW, BH) if self.mode == 'banner' else (EW, EH)

    # ----------------------------------------------------------------- open/close
    def _present(self):
        self._ensure_windows()
        self._measure_capsule()
        if time.monotonic() - self.marker_t > 20:
            self.locate()
        fx = self._target_rect()[0]
        self.L = max(0.0, min(fx - 40.0, self.screen_w - WIN_W))
        LS.set_margin(self.win, LS.Edge.LEFT, int(self.L))
        THEME.refresh(force=True)
        gfx.glass_prepare()
        self.catcher.set_visible(self.mode == 'panel')
        if self.mode == 'panel':
            self.catcher.present()
        self.win.present()
        self._start_frames()

    def open_panel(self):
        if self.is_open and self.mode == 'panel':
            return
        self.load_events(force=True)
        was_open = self.is_open
        self.mode = 'panel'
        self.banner = None
        self.is_open = True
        self.open_t = time.monotonic()
        self.tl_target = None
        self.page = 'main'
        self.page_a.snap(0)
        if not was_open:
            self._measure_capsule()
            self.sx.snap(self.cap_x)
            self.sy.snap(CAP_Y)
            self.sw.snap(self.cap_w)
            self.sh.snap(CAP_H)
            self.ca.snap(0)
        self._present()

    def close(self):
        if not self.is_open:
            return
        if self.banner is not None and self.banner.kind == 'alarm':
            # closing an alarm banner leaves the alarm ringing; the buttons decide
            pass
        self.is_open = False
        self.banner = None
        self._start_frames()
        GLib.idle_add(self._next_banner)

    def push_banner(self, b):
        if self.is_open and self.mode == 'panel':
            return          # the full island is already open: no banner needed
        if self.is_open and self.banner is not None and self.banner.kind == 'alarm' and b.kind != 'alarm':
            self.queue.append(b)
            return
        if self.is_open and self.banner is not None and b.kind != 'alarm':
            self.queue.append(b)
            return
        self._show_banner(b)

    def _show_banner(self, b):
        self.banner = b
        self.mode = 'banner'
        was_open = self.is_open
        self.is_open = True
        self.open_t = time.monotonic()
        if not was_open:
            self._measure_capsule()
            self.sx.snap(self.cap_x)
            self.sy.snap(CAP_Y)
            self.sw.snap(self.cap_w)
            self.sh.snap(CAP_H)
            self.ca.snap(0)
        self._present()
        if b.kind != 'alarm':
            play()

    def _next_banner(self):
        if self.queue and not self.is_open:
            self._show_banner(self.queue.pop(0))
        return False

    # ------------------------------------------------------------------ reminders
    def _save_fired(self):
        try:
            ids = sorted(self.fired)[-300:]
            tmp = STATE / 'island-fired.tmp'
            tmp.write_text(json.dumps(dict(ids=ids)))
            os.replace(tmp, STATE / 'island-fired.json')
        except OSError:
            pass

    def _reminders(self):
        self.load_events()
        self._split()
        now = time.time()
        p = self.prefs()
        lead = int(p.get('island_lead', LEAD_MIN))
        remind = bool(p.get('island_remind', True))
        for e in self.events:
            if e.all_day or not remind:
                continue
            until = e.start - now
            key_lead, key_start = e.id + ':lead:%d' % int(e.start), e.id + ':start:%d' % int(e.start)
            if 0 < until <= lead * 60 and key_lead not in self.fired:
                self.fired.add(key_lead)
                self._save_fired()
                self.push_banner(Banner('lead', e.title, '%s 后开始 · %s' % (fmt_left(until), hm(e.start)), event=e))
            elif -90 < until <= 0 and key_start not in self.fired:
                self.fired.add(key_start)
                self.fired.add(key_lead)
                self._save_fired()
                self.push_banner(Banner('start', e.title, '现在开始 · %s' % hm(e.start), event=e))
        return True

    def _alarm_watch(self):
        v = self.alarm_store.read()
        if v.get('status') == 'ringing' and v.get('id') != self.alarm_seen:
            self.alarm_seen = v.get('id')
            self._show_banner(Banner('alarm', '小闹钟', '时间到了，休息一下或开始下一件事。', alarm=v))
        elif self.banner is not None and self.banner.kind == 'alarm':
            if v.get('status') != 'ringing' or v.get('id') != self.banner.alarm.get('id'):
                self.close()
        if self.is_open:
            self._start_frames()
        return True

    # --------------------------------------------------------------- windows
    def _ensure_windows(self):
        if self.win is not None:
            return
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('nn-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.TOP)
        LS.set_namespace(catcher, 'notion-island-catcher')
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
        win.add_css_class('nn-island')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'notion-island')
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
        rclick.connect('released', lambda g, n, x, y: self.close())
        da.add_controller(rclick)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self._on_scroll)
        da.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._on_key)
        win.add_controller(keys)
        win.set_child(da)
        css = Gtk.CssProvider()
        css.load_from_string('window.nn-island, window.nn-catcher { background: transparent; }')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win, self.da = win, da

    # ---------------------------------------------------------------- frames
    def _start_frames(self):
        if self.win is not None and self.frame_tick is None:
            self._fl = None
            self.frame_tick = self.da.add_tick_callback(self._frame)

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        gap = .0155 if self._busy else .033
        if self._fl and now - self._fl < gap:
            return GLib.SOURCE_CONTINUE
        dt_ = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        THEME.refresh()
        self.t += dt_
        mono = time.monotonic()
        tx, ty, tw, th = self._target_rect()
        self.sx.t, self.sy.t, self.sw.t, self.sh.t = tx, ty, tw, th
        closing = not self.is_open
        for sp, (zo, wo) in ((self.sx, (.7, 15.0)), (self.sy, (.7, 15.0)), (self.sw, (.62, 16.0)), (self.sh, (.68, 12.5))):
            sp.z, sp.o = (zo, wo) if not closing else (.9, wo * 1.7)
        fw, fh = self._final_size()
        pw = (self.sw.x - self.cap_w) / max(1.0, fw - self.cap_w)
        ph = (self.sh.x - CAP_H) / max(1.0, fh - CAP_H)
        self.ca.t = 1.0 if (self.is_open and min(pw, ph) > .8) else 0.0
        busy = False
        self.page_a.t = 1.0 if self.page == 'settings' else 0.0
        for sp in (self.sx, self.sy, self.sw, self.sh, self.ca, self.tl_scroll, self.page_a) + tuple(self.press_pop.values()) + tuple(self.tog.values()):
            sp.step(dt_)
            busy = busy or not sp.settled
        if self.tl_target is not None:
            self.tl_scroll.t = float(self.tl_target)
        # banner countdown (pauses while hovered)
        if self.banner is not None and self.is_open and self.banner.kind != 'alarm':
            if self.pointer is None:
                self.banner.left -= dt_
            if self.banner.left <= 0:
                self.close()
        if time.monotonic() < self.sync_until:
            self.sync_spin += dt_ * 6
        self._busy = busy or self.is_open
        self.load_events()
        self.da.queue_draw()
        self._update_region()
        if closing and not busy:
            self.win.set_visible(False)
            self.catcher.set_visible(False)
            self.frame_tick = None
            self.region_key = None
            GLib.idle_add(self._next_banner)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _rect(self):
        return self.sx.x, self.sy.x, max(8.0, self.sw.x), max(8.0, self.sh.x)

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        key = None
        if self.is_open:
            x, y, w, h = self._rect()
            key = (int(x - self.L), int(y), int(w), int(h))
        if key == self.region_key:
            return
        self.region_key = key
        surface.set_input_region(cairo.Region([cairo.RectangleInt(*key)]) if key else cairo.Region())

    # ------------------------------------------------------------------ draw
    def draw(self, area, cr, W, H):
        try:
            self._draw_outer(cr)
        except Exception:
            import traceback
            try:
                (STATE / 'island-error.txt').write_text(traceback.format_exc())
            except OSError:
                pass

    def _draw_outer(self, cr):
        cr.translate(-self.L, 0)
        fw, _ = self._final_size()
        pw = (self.sw.x - self.cap_w) / max(1.0, fw - self.cap_w)
        fa = clamp(pw * 4.0)
        if fa < .01:
            return
        if fa < .995:
            cr.push_group()
            self._draw(cr)
            cr.pop_group_to_source()
            cr.paint_with_alpha(fa)
        else:
            self._draw(cr)

    def _draw(self, cr):
        x, y, w, h = self._rect()
        fw, fh = self._final_size()
        ph = clamp((self.sh.x - CAP_H) / max(1.0, fh - CAP_H))
        rad = lerp(13.5, 30.0 if self.mode == 'panel' else 26.0, ph)
        sa = clamp(ph * 1.4)
        if sa > .02:
            cr.save()
            cr.translate(x, y)
            cr.scale(w / fw, h / fh)
            cr.push_group()
            gfx.shadow(cr, 0, 0, fw, fh, 30, 1.5, 10)
            cr.pop_group_to_source()
            cr.paint_with_alpha(sa)
            cr.restore()
        rrect(cr, x, y, w, h, rad)
        gfx.glass_origin(self.L, 0)
        gfx.panel_fill(cr, BLACK, .07)
        ca = clamp(self.ca.x)
        if ca > .01:
            cr.save()
            rrect(cr, x, y, w, h, rad)
            cr.clip()
            cr.translate(x, y)
            self.zones = []
            self.local = None if self.pointer is None else (self.pointer[0] - x, self.pointer[1] - y)
            cr.translate(0, (1 - ca) * 8)
            cr.push_group()
            if self.mode == 'banner' and self.banner is not None:
                self._draw_banner(cr)
            else:
                self._draw_panel(cr)
            cr.pop_group_to_source()
            cr.paint_with_alpha(ca)
            cr.restore()

    # ---- zones
    def _zone(self, key, shape, *a):
        self.zones.append((key, shape, a))
        p = self.local
        return p is not None and self._inside(shape, a, p)

    @staticmethod
    def _inside(shape, a, p):
        if shape == 'c':
            cx, cy, r = a
            return (p[0] - cx) ** 2 + (p[1] - cy) ** 2 <= r * r
        x, y, w, h = a
        return x <= p[0] <= x + w and y <= p[1] <= y + h

    def _pop(self, key):
        sp = self.press_pop.get(key)
        return 1.0 + (sp.x if sp else 0.0)

    def _press(self, key):
        sp = self.press_pop.get(key)
        if sp is None:
            sp = self.press_pop[key] = Spring(0, omega=26, zeta=.35)
        sp.x, sp.v, sp.t = -.18, 0.0, 0.0

    def _round_btn(self, cr, key, cx, cy, r, drawer, tint=(1, 1, 1), spin=0.0):
        hot = self._zone(key, 'c', cx, cy, r + 3)
        s = self._pop(key)
        cr.save()
        cr.translate(cx, cy)
        cr.scale(s, s)
        cr.arc(0, 0, r, 0, math.tau)
        cr.set_source_rgba(*tint, .2 if hot else .09)
        cr.fill()
        if spin:
            cr.rotate(spin)
        drawer(cr, 0, 0, r * .8, (*tint, .95))
        cr.restore()

    def _chip(self, cr, key, x, y, w, h, label, active, col, txt):
        hot = self._zone(key, 'r', x, y, w, h)
        rrect(cr, x, y, w, h, h / 2)
        cr.set_source_rgba(*(col if active else txt), .3 if active else (.14 if hot else .07))
        cr.fill()
        ctext(cr, label, 12.5, True, x + w / 2, y + h / 2, (*(col if active else txt), 1.0 if active else .78))

    # ---------------------------------------------------------------- panel
    def _current_next(self, now):
        active = [e for e in self.day_events if not e.point and e.start <= now < e.end]
        active.sort(key=lambda e: (e.end, e.id))
        upcoming = [e for e in self.day_events if e.start > now]
        upcoming.sort(key=lambda e: (e.start, e.id))
        return active, (upcoming[0] if upcoming else None)

    PREF_DEFAULTS = dict(display_mode='pinned', max_visible=2, title_limit=18, rotate_seconds=5, accent_color=False,
                         show_progress=True, end_warning=True, end_warning_minutes=5, notify_switch=True,
                         island_remind=True, island_lead=5)
    STEPS = dict(max_visible=(1, 5, 1, ' 项'), title_limit=(8, 28, 1, ' 字'), rotate_seconds=(2, 15, 1, ' 秒'),
                 end_warning_minutes=(1, 30, 1, ' 分钟'), island_lead=(1, 30, 1, ' 分钟'))

    def prefs(self):
        now = time.monotonic()
        if now - self._prefs_t > 1.0:
            self._prefs_t = now
            v = read_json(STATE / 'preferences.json')
            self._prefs = dict(self.PREF_DEFAULTS, **(v if isinstance(v, dict) else {}))
        return self._prefs

    def save_pref(self, key, value):
        cur = read_json(STATE / 'preferences.json')
        cur = cur if isinstance(cur, dict) else {}
        cur[key] = value
        try:
            tmp = STATE / 'preferences.tmp'
            tmp.write_text(json.dumps(cur, ensure_ascii=False))
            os.replace(tmp, STATE / 'preferences.json')
        except OSError:
            return
        self._prefs = dict(self.PREF_DEFAULTS, **cur)
        self._prefs_t = time.monotonic()
        self.saved_at = time.monotonic()

    def _draw_panel(self, cr):
        th = THEME
        txt, acc = th.text, th.accent
        now = time.time()
        today = dt.date.today()
        since = time.monotonic() - self.open_t
        pg = clamp(self.page_a.x)
        # ---- header (shared)
        wiggle = clamp(1 - (since - .35) / .9) if since > .35 else 0.0
        draw_calendar(cr, 38, 40, 17, today.day, self.t, wiggle)
        cr.push_group()
        dl(cr, gfx.text_layout('日程', 22, True), 68, 18, (*txt, 1))
        dl(cr, gfx.text_layout('%d月%d日 周%s' % (today.month, today.day, WEEKDAY[today.weekday()]), 13), 69, 50, (*txt, .6))
        cr.pop_group_to_source()
        cr.paint_with_alpha(1 - pg)
        if pg > .01:
            cr.push_group()
            dl(cr, gfx.text_layout('偏好设置', 22, True), 68, 18, (*txt, 1))
            dl(cr, gfx.text_layout('日程 · 修改后自动保存', 13), 69, 50, (*txt, .6))
            cr.pop_group_to_source()
            cr.paint_with_alpha(pg)
        main_on = pg < .5
        saved = time.monotonic() - self.saved_at < 1.6
        if main_on:
            self._round_btn(cr, 'refresh', EW - 74, 40, 15, icon_reset, txt, spin=self.sync_spin if time.monotonic() < self.sync_until else 0.0)
            self._round_btn(cr, 'page:settings', EW - 36, 40, 15, draw_gear, txt)
        else:
            self._round_btn(cr, 'page:main', EW - 36, 40, 15, icon_back, txt)
        # ---- main page
        if pg < .99:
            cr.save()
            cr.push_group()
            cr.translate(-pg * 36, 0)
            keep = self.zones
            if not main_on:
                self.zones = []
            self._draw_main(cr, now, txt, acc, since)
            if not main_on:
                self.zones = keep
            cr.pop_group_to_source()
            cr.paint_with_alpha(1 - pg)
            cr.restore()
        if pg > .01:
            cr.save()
            cr.push_group()
            cr.translate((1 - pg) * 36, 0)
            keep = self.zones
            if main_on:
                self.zones = []
            self._draw_settings(cr, now, txt, acc, saved)
            if main_on:
                self.zones = keep
            cr.pop_group_to_source()
            cr.paint_with_alpha(pg)
            cr.restore()

    def _draw_main(self, cr, now, txt, acc, since):
        active, nxt = self._current_next(now)
        cx0, cy0, cw, chh = 16.0, 76.0, EW - 32, 100.0
        hero_ev = active[0] if active else nxt
        if hero_ev is not None:
            # the zone must be in island coordinates (the hero itself is drawn in a translated frame)
            self._zone('url:' + hero_ev.id, 'r', cx0, cy0, cw, chh)
        reveal = ease_back((since - .12) / .4)
        cr.save()
        cr.translate(cx0 + cw / 2, cy0 + chh / 2)
        cr.scale(max(.01, reveal), max(.01, reveal))
        cr.translate(-cw / 2, -chh / 2)
        self._hero(cr, 0, 0, cw, chh, now, active, nxt, txt, acc)
        cr.restore()
        y = 188.0
        if self.all_day:
            x = 18.0
            for e in self.all_day[:4]:
                lay = gfx.text_layout(e.title if len(e.title) <= 8 else e.title[:8] + '…', 12, True)
                w = gfx.text_size(lay)[0] + 28
                if x + w > EW - 16:
                    break
                hot = self._zone('url:' + e.id, 'r', x, y, w, 24)
                rrect(cr, x, y, w, 24, 12)
                cr.set_source_rgba(*e.col, .32 if hot else .2)
                cr.fill()
                cr.arc(x + 12, y + 12, 3.2, 0, math.tau)
                cr.set_source_rgba(*e.col, 1)
                cr.fill()
                dl(cr, lay, x + 20, y + (24 - gfx.text_size(lay)[1]) / 2, (*txt, .9))
                x += w + 8
            y += 32
        self._vtimeline(cr, now, y, EH - 116, txt, acc, since)
        self._alarm_row(cr, now, EH - 104, txt, acc)
        self._footer(cr, now, EH - 38, txt, acc)

    # --------------------------------------------------------------- settings
    def _draw_settings(self, cr, now, txt, acc, saved):
        p = self.prefs()
        # sub-tabs
        x0, y0, w, h = 16.0, 84.0, EW - 32, 32.0
        rrect(cr, x0, y0, w, h, 16)
        cr.set_source_rgba(*txt, .07)
        cr.fill()
        tabs = (('bar', '顶栏'), ('remind', '提醒'), ('conn', '连接'))
        cw = w / 3
        idx = [t[0] for t in tabs].index(self.stab)
        rrect(cr, x0 + 3 + cw * idx, y0 + 3, cw - 6, h - 6, 13)
        cr.set_source_rgba(*acc, .3)
        cr.fill()
        for i, (k, lab) in enumerate(tabs):
            hot = self._zone('stab:' + k, 'r', x0 + cw * i, y0, cw, h)
            ctext(cr, lab, 13, True, x0 + cw * (i + .5), y0 + h / 2, (*txt, 1.0 if k == self.stab else (.8 if hot else .55)))
        y = 130.0
        if self.stab == 'bar':
            dl(cr, gfx.text_layout('活动如何显示', 12, True), 24, y, (*txt, .5))
            y += 22
            y = self._seg(cr, 'display_mode', (('pinned', '主日程'), ('parallel', '同时显示'), ('rotate', '自动轮播')), p, y, txt, acc)
            if p['display_mode'] == 'parallel':
                y = self._stepper(cr, 'max_visible', '同时显示数量', p, y, txt, acc)
            if p['display_mode'] == 'rotate':
                y = self._stepper(cr, 'rotate_seconds', '轮播间隔', p, y, txt, acc)
            y = self._stepper(cr, 'title_limit', '标题最多显示', p, y, txt, acc)
            y = self._toggle(cr, 'accent_color', '主题强调色', '胶囊里的文字使用主题强调色', p, y, txt, acc)
            y = self._toggle(cr, 'show_progress', '活动进度条', '胶囊底部显示当前活动的进度', p, y, txt, acc)
        elif self.stab == 'remind':
            y = self._toggle(cr, 'island_remind', '开始前弹出提醒横幅', '日程快开始时，灵动岛自动弹出并提示', p, y, txt, acc)
            if p['island_remind']:
                y = self._stepper(cr, 'island_lead', '提前多久', p, y, txt, acc)
            y = self._toggle(cr, 'end_warning', '临近结束变色', '剩余时间不足时，进度条变为橙色', p, y, txt, acc)
            if p['end_warning']:
                y = self._stepper(cr, 'end_warning_minutes', '提前多久', p, y, txt, acc)
            self._chip(cr, 'set:preview', 24, y + 8, 120, 30, '预览提醒横幅', False, acc, txt)
        else:
            ok = self.sync.get('ok', True) is not False
            col = (.45, .85, .6) if ok else (1.0, .5, .45)
            cr.arc(32, y + 12, 4, 0, math.tau)
            cr.set_source_rgba(*col, 1)
            cr.fill()
            msg = '已连接 · 自动同步中' if ok else (self.sync.get('message') or '尚未连接')
            dl(cr, gfx.text_layout(msg if len(msg) <= 22 else msg[:22] + '…', 14, True), 46, y + 2, (*txt, 1))
            dl(cr, gfx.text_layout('每两分钟读取一次最新日程，密钥保存在本机。', 12), 24, y + 34, (*txt, .5))
            self._chip(cr, 'conn:manage', 24, y + 66, 150, 32, '管理 Notion 连接', True, acc, txt)
            self._chip(cr, 'refresh', 184, y + 66, 100, 32, '立即同步', False, acc, txt)
        # saved indicator
        a = .9 if saved else .35
        dl(cr, gfx.text_layout('● 已自动保存' if saved else '修改后自动保存', 11.5), 24, EH - 34, (*((.45, .85, .6) if saved else txt), a))

    def _toggle(self, cr, key, title, hint, p, y, txt, acc):
        on = bool(p.get(key))
        sp = self.tog.get(key)
        if sp is None:
            sp = self.tog[key] = Spring(1.0 if on else 0.0, omega=26, zeta=.6)
        sp.t = 1.0 if on else 0.0
        hot = self._zone('set:' + key, 'r', 16, y, EW - 32, 52)
        rrect(cr, 16, y, EW - 32, 52, 14)
        cr.set_source_rgba(*txt, .08 if hot else .035)
        cr.fill()
        dl(cr, gfx.text_layout(title, 14, True), 28, y + 8, (*txt, 1))
        dl(cr, gfx.text_layout(hint, 11.5), 28, y + 29, (*txt, .5))
        tx, ty = EW - 78, y + 14
        rrect(cr, tx, ty, 46, 24, 12)
        k = clamp(sp.x)
        cr.set_source_rgba(*[lerp(txt[i] * .35, acc[i], k) for i in range(3)], 1)
        cr.fill()
        cr.arc(tx + 12 + 22 * sp.x, ty + 12, 9.2, 0, math.tau)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.fill()
        return y + 58

    def _stepper(self, cr, key, title, p, y, txt, acc):
        lo, hi, step, suffix = self.STEPS[key]
        v = int(p.get(key, lo))
        rrect(cr, 16, y, EW - 32, 44, 14)
        cr.set_source_rgba(*txt, .035)
        cr.fill()
        dl(cr, gfx.text_layout(title, 14, True), 28, y + 12, (*txt, 1))
        self._round_btn(cr, 'step:%s:-1' % key, EW - 128, y + 22, 13, lambda c, x, yy, sz, col: icon_plus(c, x, yy, sz, col, True), txt)
        ctext(cr, '%d%s' % (v, suffix), 13, True, EW - 84, y + 22, (*txt, 1))
        self._round_btn(cr, 'step:%s:1' % key, EW - 40, y + 22, 13, icon_plus, txt)
        return y + 50

    def _seg(self, cr, key, options, p, y, txt, acc):
        x0, w, h = 16.0, EW - 32, 34.0
        rrect(cr, x0, y, w, h, 17)
        cr.set_source_rgba(*txt, .07)
        cr.fill()
        cw = w / len(options)
        cur = p.get(key)
        ids = [o[0] for o in options]
        i = ids.index(cur) if cur in ids else 0
        sp = self.tog.get('seg:' + key)
        if sp is None:
            sp = self.tog['seg:' + key] = Spring(i, omega=20, zeta=.75)
        sp.t = float(i)
        rrect(cr, x0 + 3 + cw * sp.x, y + 3, cw - 6, h - 6, 14)
        cr.set_source_rgba(*acc, .85)
        cr.fill()
        for j, (k, lab) in enumerate(options):
            hot = self._zone('seg:%s:%s' % (key, k), 'r', x0 + cw * j, y, cw, h)
            ctext(cr, lab, 13, True, x0 + cw * (j + .5), y + h / 2, (1, 1, 1, 1) if j == i else (*txt, .85 if hot else .6))
        return y + h + 12

    def _hero(self, cr, x, y, w, h, now, active, nxt, txt, acc):
        rrect(cr, x, y, w, h, 22)
        if active:
            e = active[0]
            g = cairo.LinearGradient(x, y, x + w, y + h)
            g.add_color_stop_rgba(0, *e.col, .34)
            g.add_color_stop_rgba(1, *e.col, .1)
            cr.set_source(g)
            cr.fill_preserve()
            cr.set_source_rgba(*e.col, .5)
            cr.set_line_width(1.2)
            cr.stroke()
            dl(cr, gfx.text_layout('进行中', 11.5, True), x + 20, y + 14, (*e.col, 1))
            title = gfx.text_layout(e.title if len(e.title) <= 15 else e.title[:15] + '…', 20, True)
            dl(cr, title, x + 20, y + 32, (*txt, 1))
            dl(cr, gfx.text_layout('%s – %s' % (hm(e.start), hm(e.end)), 13), x + 20, y + 62, (*txt, .6))
            frac = clamp((now - e.start) / max(1.0, e.end - e.start))
            rrect(cr, x + 20, y + h - 22, w - 148, 6, 3)
            cr.set_source_rgba(*txt, .12)
            cr.fill()
            rrect(cr, x + 20, y + h - 22, max(6.0, (w - 148) * frac), 6, 3)
            cr.set_source_rgba(*e.col, 1)
            cr.fill()
            self._ring(cr, x + w - 56, y + h / 2, 34, 1 - frac, e.col, fmt_left(e.end - now), txt)
        elif nxt is not None:
            e = nxt
            cr.set_source_rgba(*txt, .06)
            cr.fill_preserve()
            cr.set_source_rgba(*txt, .12)
            cr.set_line_width(1)
            cr.stroke()
            dl(cr, gfx.text_layout('接下来', 11.5, True), x + 20, y + 14, (*acc, 1))
            dl(cr, gfx.text_layout(e.title if len(e.title) <= 15 else e.title[:15] + '…', 20, True), x + 20, y + 32, (*txt, 1))
            dl(cr, gfx.text_layout('%s 开始' % hm(e.start), 13), x + 20, y + 62, (*txt, .6))
            soon = clamp(1 - (e.start - now) / 10800.0)
            self._ring(cr, x + w - 56, y + h / 2, 34, soon, acc, fmt_left(e.start - now), txt)
        else:
            cr.set_source_rgba(*txt, .05)
            cr.fill()
            draw_cup(cr, x + 62, y + 54, 34, self.t)
            ok = self.sync.get('ok', True) is not False
            dl(cr, gfx.text_layout('今天没有日程', 20, True), x + 118, y + 22, (*txt, 1))
            sub = '好好休息一下吧' if ok else 'Notion 同步失败：' + str(self.sync.get('message', '网络连接失败'))[:14]
            dl(cr, gfx.text_layout(sub, 13), x + 119, y + 56, (*((1, .55, .5) if not ok else txt), .65))

    def _ring(self, cr, cx, cy, r, frac, col, label, txt):
        cr.set_line_width(6)
        cr.set_line_cap(1)
        cr.new_path()
        cr.arc(cx, cy, r, 0, math.tau)
        cr.set_source_rgba(*txt, .1)
        cr.stroke()
        if frac > .003:
            cr.new_path()
            cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + math.tau * clamp(frac))
            cr.set_source_rgba(*col, 1)
            cr.stroke()
        parts = label.split(' ', 1)
        live(cr, parts[0], 17, True, cx, cy - 6, (*txt, 1))
        live(cr, parts[1] if len(parts) > 1 else '', 11, False, cx, cy + 12, (*txt, .55))

    # ------------------------------------------------------------ day timeline
    PXH = 56.0                      # pixels per hour in the vertical timeline

    def _tl_view(self, y0, y1):
        return (y1 - y0) / self.PXH

    def _tl_goto_now(self, y0, y1, now):
        vis = self._tl_view(y0, y1)
        h = (now - self.day_start) / 3600
        self.tl_target = max(0.0, min(24 - vis, h - 1.2))

    def _vtimeline(self, cr, now, y0, y1, txt, acc, since):
        """Vertical day view: the events themselves are the timeline (sized by duration), scroll to pan."""
        vis = self._tl_view(y0, y1)
        if self.tl_target is None:
            self._tl_goto_now(y0, y1, now)
            self.tl_scroll.snap(self.tl_target)
        self.tl_target = max(0.0, min(24 - vis, self.tl_target))
        off = self.tl_scroll.x
        x0, x1 = 58.0, EW - 18.0
        cr.save()
        cr.rectangle(0, y0, EW, y1 - y0)
        cr.clip()
        reveal = clamp((since - .2) / .4)
        # hour lines
        for hr in range(int(off) - 1, int(off + vis) + 2):
            if hr < 0 or hr > 24:
                continue
            yy = y0 + (hr - off) * self.PXH
            cr.set_source_rgba(*txt, .1 * reveal)
            cr.set_line_width(1)
            cr.move_to(x0 - 4, yy)
            cr.line_to(x1, yy)
            cr.stroke()
            if hr < 24:
                dl(cr, gfx.text_layout('%02d:00' % hr, 10.5), 20, yy - 6, (*txt, .45 * reveal))
        # lane layout: events that overlap in time share the row, side by side
        evs = [e for e in self.day_events]
        cols = {}
        ncols = {}
        cluster = []
        cluster_end = 0.0

        def flush():
            if not cluster:
                return
            lanes = []
            for e in cluster:
                lane = 0
                while lane < len(lanes) and lanes[lane] > e.start + 1:
                    lane += 1
                if lane == len(lanes):
                    lanes.append(0)
                lanes[lane] = max(e.end, e.start + 1200)
                cols[e.id] = lane
            for e in cluster:
                ncols[e.id] = len(lanes)
        for e in evs:
            if cluster and e.start >= cluster_end:
                flush()
                cluster = []
            cluster.append(e)
            cluster_end = max(cluster_end, e.end, e.start + 1200)
        flush()
        order = 0
        for e in evs:
            sh = (e.start - self.day_start) / 3600
            eh = max(sh + .4, (e.end - self.day_start) / 3600) if not e.point else sh + .4
            if eh < off - .2 or sh > off + vis + .2:
                continue
            n = ncols.get(e.id, 1)
            lane = cols.get(e.id, 0)
            gap = 4.0
            cw = (x1 - x0 - gap * (n - 1)) / n
            cx = x0 + lane * (cw + gap)
            cy = y0 + (sh - off) * self.PXH + 1
            chh = max(24.0, (eh - sh) * self.PXH - 3)
            order += 1
            appear = ease_back((since - .22 - order * .045) / .38)
            if appear <= .01:
                continue
            hot = cy + chh > y0 and cy < y1 and self._zone('url:' + e.id, 'r', cx, max(cy, y0), cw, min(cy + chh, y1) - max(cy, y0))
            past = e.end < now and not e.point
            running = e.start <= now < e.end
            cr.save()
            cr.translate(cx + cw / 2, cy + chh / 2)
            cr.scale(max(.01, min(1.0, appear)), max(.01, appear))
            cr.translate(-cw / 2, -chh / 2)
            rrect(cr, 0, 0, cw, chh, 9)
            a_bg = .4 if running else (.1 if past else .2)
            cr.set_source_rgba(*e.col, a_bg + (.1 if hot else 0))
            cr.fill()
            if running:
                rrect(cr, 0, 0, cw, chh, 9)
                cr.set_source_rgba(*e.col, .75)
                cr.set_line_width(1.2)
                cr.stroke()
            cr.save()
            rrect(cr, 0, 0, cw, chh, 9)
            cr.clip()
            cr.rectangle(0, 0, 3.5, chh)
            cr.set_source_rgba(*e.col, .45 if past else 1)
            cr.fill()
            a_txt = .4 if past else 1.0
            if cw > 40:
                lay = gfx.make_layout(e.title, 12.5, True, width=cw - 18, lines=2 if chh > 44 else 1)
                dl(cr, lay, 11, 5, (*txt, a_txt))
                th = gfx.text_size(lay)[1]
                if chh > th + 24:
                    dl(cr, gfx.text_layout('%s – %s' % (hm(e.start), hm(e.end)) if not e.point else hm(e.start), 10.5), 11, 5 + th + 2, (*txt, a_txt * .6))
            cr.restore()
            cr.restore()
        # now line
        nh = (now - self.day_start) / 3600
        if off - .2 <= nh <= off + vis + .2:
            ny = y0 + (nh - off) * self.PXH
            pulse = .5 + .5 * math.sin(self.t * 3)
            cr.set_source_rgba(*acc, .9)
            cr.set_line_width(1.6)
            cr.move_to(x0 - 10, ny)
            cr.line_to(x1, ny)
            cr.stroke()
            cr.arc(x0 - 10, ny, 3.6 + pulse * 1.3, 0, math.tau)
            cr.fill()
            lab = gfx.text_layout(time.strftime('%H:%M', time.localtime(now)), 10.5, True)
            lw = gfx.text_size(lab)[0] + 10
            rrect(cr, 6, ny - 9, lw, 18, 9)
            cr.set_source_rgba(*acc, 1)
            cr.fill()
            dl(cr, lab, 11, ny - 8, (1, 1, 1, 1))
        cr.restore()
        # fades at the edges + "back to now" pill when it is off screen
        for (yy, d) in ((y0, 1), (y1 - 14, -1)):
            g = cairo.LinearGradient(0, yy, 0, yy + 14 if d > 0 else yy)
            g.add_color_stop_rgba(0, *BLACK, 1 if d > 0 else 0)
            g.add_color_stop_rgba(1, *BLACK, 0 if d > 0 else 1)
        if not (off - .1 <= nh <= off + vis + .1):
            top = nh < off
            self._chip(cr, 'tl:now', EW - 96, (y0 + 6) if top else (y1 - 32), 78, 26, '↑ 现在' if top else '↓ 现在', True, acc, txt)
        if not evs:
            ctext(cr, '今天没有日程 · 空闲的一天', 12, False, EW / 2 + 20, (y0 + y1) / 2, (*txt, .35))

    def _alarm_row(self, cr, now, y, txt, acc):
        v = self.alarm_store.read()
        scheduled = v.get('status') == 'scheduled' and isinstance(v.get('due'), (int, float)) and v['due'] > now
        cr.set_source_rgba(*txt, .08)
        cr.set_line_width(1)
        cr.move_to(20, y - 8)
        cr.line_to(EW - 20, y - 8)
        cr.stroke()
        draw_bell(cr, 30, y + 14, 13, self.t, 1.0 if scheduled and v['due'] - now < 10 else 0.0, (*acc,))
        dl(cr, gfx.text_layout('小闹钟', 13, True), 46, y + 4, (*txt, .9))
        if scheduled:
            left = v['due'] - now
            live(cr, fmt_left(left) if left < 60 else '%02d:%02d' % divmod(int(left), 60), 14, True, 130, y + 14, (*acc, 1), left=True)
            self._chip(cr, 'alarm:cancel', EW - 92, y + 1, 72, 26, '取消', False, acc, txt)
        else:
            cw = (EW - 110 - 16) / 5
            for i, (m, lab) in enumerate(ALARM_CHIPS):
                self._chip(cr, 'alarm:%d' % m, 104 + (cw + 4) * i, y + 1, cw, 26, lab, False, acc, txt)

    def _footer(self, cr, now, y, txt, acc):
        ok = self.sync.get('ok', True) is not False
        updated = float(self.sync.get('updated') or self.sync_updated or 0)
        col = (.45, .85, .6) if ok else (1.0, .5, .45)
        pulse = .6 + .4 * math.sin(self.t * 3)
        cr.arc(24, y + 11, 3.5, 0, math.tau)
        cr.set_source_rgba(*col, pulse if time.monotonic() < self.sync_until else 1)
        cr.fill()
        ago = '' if not updated else ('刚刚' if now - updated < 60 else '%d 分钟前' % int((now - updated) / 60))
        state = '同步中…' if time.monotonic() < self.sync_until else (('已同步 · ' + ago) if ok else '同步失败 · ' + ago)
        dl(cr, gfx.text_layout(state, 11.5), 36, y + 3, (*txt, .55))
        self._chip(cr, 'page:settings', EW - 80, y - 3, 62, 26, '设置', False, acc, txt)

    # ---------------------------------------------------------------- banner
    def _draw_banner(self, cr):
        th = THEME
        txt, acc = th.text, th.accent
        b = self.banner
        now = time.time()
        since = time.monotonic() - self.open_t
        alarm = b.kind == 'alarm'
        col = (1.0, .5, .4) if alarm else (b.event.col if b.event else acc)
        # icon: wiggling bell (alarm) or calendar
        pop = ease_back((since - .1) / .4)
        cr.save()
        cr.translate(48, 52)
        cr.scale(max(.01, pop), max(.01, pop))
        if alarm:
            cr.arc(0, 0, 26, 0, math.tau)
            cr.set_source_rgba(*col, .22)
            cr.fill()
            draw_bell(cr, 0, 2, 22, self.t, 1.0, col)
        else:
            draw_calendar(cr, 0, 0, 17, dt.date.today().day, self.t, 1.0 if since < 2.5 else 0.0, col)
        cr.restore()
        head = {'lead': '即将开始', 'start': '现在开始', 'alarm': '时间到'}.get(b.kind, '提醒')
        dl(cr, gfx.text_layout(head, 11.5, True), 90, 14, (*col, 1))
        # the title gets the whole row (the buttons sit on their own row below), ellipsised if it is still too long
        dl(cr, gfx.make_layout(b.title, 19, True, width=BW - 90 - 22, lines=1), 90, 31, (*txt, 1))
        dl(cr, gfx.make_layout(b.sub, 12.5, False, width=BW - 90 - 22, lines=1), 91, 62, (*txt, .6))
        by = BH - 54
        if alarm:
            self._chip(cr, 'banner:snooze', BW - 176, by, 92, 28, '再提醒5分', False, col, txt)
            self._chip(cr, 'banner:dismiss', BW - 76, by, 60, 28, '关闭', True, col, txt)
        else:
            self._chip(cr, 'banner:open', BW - 168, by, 80, 28, '查看日程', False, col, txt)
            self._chip(cr, 'banner:dismiss', BW - 80, by, 64, 28, '知道了', True, col, txt)
            frac = clamp(b.left / BANNER_SECONDS)
            rrect(cr, 24, BH - 14, BW - 48, 3, 1.5)
            cr.set_source_rgba(*txt, .1)
            cr.fill()
            rrect(cr, 24, BH - 14, max(3.0, (BW - 48) * frac), 3, 1.5)
            cr.set_source_rgba(*col, .9)
            cr.fill()

    # ----------------------------------------------------------------- input
    def _on_motion(self, ctl, x, y):
        self.pointer = (x + self.L, y)
        self._start_frames()

    def _on_leave(self, ctl):
        self.pointer = None
        self._start_frames()

    def _on_click(self, g, n, x, y):
        if not self.is_open:
            return
        bx, by, _, _ = self._rect()
        p = (x + self.L - bx, y - by)
        hit = None
        for key, shape, a in reversed(self.zones):
            if self._inside(shape, a, p):
                hit = key
                self._act(key)
                break
        try:
            with open(STATE / 'island-click.log', 'a') as f:
                f.write('%.0f page=%s local=(%.0f,%.0f) hit=%s\n' % (time.time(), self.page, p[0], p[1], hit))
        except OSError:
            pass
        self._start_frames()

    def _act(self, key):
        self._press(key)
        parts = key.split(':')
        kind = parts[0]
        if key == 'refresh':
            if time.monotonic() >= self.sync_until:                  # one sync at a time
                self.sync_base = self.sync_updated
                spawn(['systemctl', '--user', 'start', 'notion-now-sync.service'])
                self.sync_until = time.monotonic() + 30.0         # spins until the data actually updates
        elif key == 'page:settings':
            self.page = 'settings'
        elif key == 'page:main':
            self.page = 'main'
        elif kind == 'stab':
            self.stab = parts[1]
        elif kind == 'set':
            if parts[1] == 'preview':
                self.is_open = False
                GLib.timeout_add(280, lambda: self.push_banner(Banner('lead', '设计评审', '5 分钟后开始 · %s' % hm(time.time() + 300))) or False)
            else:
                self.save_pref(parts[1], not bool(self.prefs().get(parts[1])))
        elif kind == 'step':
            k, d = parts[1], int(parts[2])
            lo, hi, step, _ = self.STEPS[k]
            self.save_pref(k, max(lo, min(hi, int(self.prefs().get(k, lo)) + d * step)))
        elif kind == 'seg':
            self.save_pref(parts[1], parts[2])
        elif key == 'conn:manage':
            spawn(['python3', str(HERE / 'calendar_bridge.py'), 'setup'])
        elif key == 'tl:now':
            self.tl_target = None
        elif key.startswith('alarm:'):
            what = key.split(':')[1]
            if what == 'cancel':
                self.alarm_store.cancel()
            else:
                try:
                    self.alarm_store.schedule(time.time() + int(what) * 60)
                except ValueError:
                    pass
        elif key.startswith('url:'):
            eid = key[4:]
            for e in self.events:
                if e.id == eid and e.url:
                    spawn(['xdg-open', e.url])
        elif key == 'banner:dismiss':
            b = self.banner
            if b is not None and b.kind == 'alarm' and b.alarm:
                self.alarm_store.cancel(b.alarm.get('id'))
            self.close()
        elif key == 'banner:snooze':
            b = self.banner
            if b is not None and b.alarm:
                self.alarm_store.snooze(b.alarm.get('id'))
            self.close()
        elif key == 'banner:open':
            self.is_open = False
            self.banner = None
            GLib.timeout_add(260, lambda: self.open_panel() or False)

    def _on_scroll(self, ctl, dx, dy):
        if self.is_open and self.mode == 'panel' and self.page == 'main' and abs(dy) > .01:
            if self.tl_target is None:
                self.tl_target = self.tl_scroll.x
            self.tl_target += 1.0 if dy > 0 else -1.0
            self._start_frames()
        return True

    def _on_key(self, ctl, keyval, keycode, state):
        name = Gdk.keyval_name(keyval)
        if name == 'Escape':
            self.close()
            return True
        return False


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    lock = open(STATE / 'island.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    app = Gtk.Application(application_id='dev.pr.NotionIsland', flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def on_activate(a):
        a.hold()
        holder['island'] = NotionIsland(a)

    app.connect('activate', on_activate)
    app.run([])


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Media island: the bar's media capsule morphs into a black dynamic island with the player.

Cover art that breathes with the music, a wavy progress line, a play button that morphs, volume, player chooser.
Reads the same status.json as the capsule and sends commands through the capsule's command socket.
Commands for the island arrive in ~/.local/state/media-capsule/island-cmd.json (written by widget.luau).
"""
import fcntl
import json
import math
import os
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
from PIL import Image  # noqa: E402

import barpos  # noqa: E402
import gfx  # noqa: E402
from clock_island import dl, ease_back, mask_text, live, ctext  # noqa: E402
from gfx import THEME, Spring, clamp, lerp, rrect  # noqa: E402
from media_canvas import STATE, cover_surface, deliver, read  # noqa: E402

BLACK = (.012, .012, .018)
CAP_H, CAP_Y = 26.0, 7.0
EW, EH = 392.0, 548.0
WIN_W, WIN_H = 460, 600
COVER = 212.0


def clock_text(seconds):
    seconds = max(0, int(seconds))
    return '%d:%02d' % (seconds // 60, seconds % 60)


def dominant_colour(url):
    """A saturated average colour of the cover (for the glow behind it)."""
    from urllib.parse import unquote, urlparse
    p = urlparse(url or '')
    if p.scheme != 'file':
        return None
    try:
        with Image.open(Path(unquote(p.path))) as im:
            im = im.convert('RGB').resize((24, 24))
            px = list(im.getdata())
    except (OSError, ValueError):
        return None
    best, score = None, -1.0
    for (r, g, b) in px:
        mx, mn = max(r, g, b), min(r, g, b)
        sat = (mx - mn) / (mx + 1)
        s = sat * (mx / 255.0 + .2)
        if s > score:
            best, score = (r, g, b), s
    if best is None:
        return None
    return tuple(min(1.0, v / 255.0 * 1.15) for v in best)


def icon_prev(cr, cx, cy, s, col):
    cr.set_source_rgba(*col)
    cr.move_to(cx + s * .38, cy - s * .42)
    cr.line_to(cx - s * .22, cy)
    cr.line_to(cx + s * .38, cy + s * .42)
    cr.close_path()
    cr.fill()
    rrect(cr, cx - s * .42, cy - s * .42, s * .14, s * .84, s * .05)
    cr.fill()


def icon_next(cr, cx, cy, s, col):
    cr.set_source_rgba(*col)
    cr.move_to(cx - s * .38, cy - s * .42)
    cr.line_to(cx + s * .22, cy)
    cr.line_to(cx - s * .38, cy + s * .42)
    cr.close_path()
    cr.fill()
    rrect(cr, cx + s * .28, cy - s * .42, s * .14, s * .84, s * .05)
    cr.fill()


def icon_playpause(cr, cx, cy, s, col, p):
    """p = 0 play (triangle) .. 1 pause (two bars); both are drawn, cross-fading and turning slightly."""
    p = clamp(p)
    cr.save()
    cr.translate(cx, cy)
    if p < .995:
        cr.save()
        cr.rotate(p * .6)
        cr.scale(1 - p * .35, 1 - p * .35)
        cr.set_source_rgba(*col[:3], col[3] * (1 - p))
        cr.move_to(-s * .3, -s * .5)
        cr.line_to(s * .55, 0)
        cr.line_to(-s * .3, s * .5)
        cr.close_path()
        cr.fill()
        cr.restore()
    if p > .005:
        cr.save()
        cr.rotate((p - 1) * .6)
        cr.scale(.65 + p * .35, .65 + p * .35)
        cr.set_source_rgba(*col[:3], col[3] * p)
        for dx in (-.3, .3):
            rrect(cr, dx * s - s * .15, -s * .5, s * .3, s, s * .08)
            cr.fill()
        cr.restore()
    cr.restore()


def icon_speaker(cr, cx, cy, s, col, level):
    cr.set_source_rgba(*col)
    cr.move_to(cx - s * .5, cy - s * .2)
    cr.line_to(cx - s * .25, cy - s * .2)
    cr.line_to(cx + s * .05, cy - s * .48)
    cr.line_to(cx + s * .05, cy + s * .48)
    cr.line_to(cx - s * .25, cy + s * .2)
    cr.line_to(cx - s * .5, cy + s * .2)
    cr.close_path()
    cr.fill()
    cr.set_line_width(max(1.3, s * .12))
    cr.set_line_cap(1)
    for i, r in enumerate((.3, .55)):
        if level > (i + .3) / 2.2:
            cr.arc(cx + s * .05, cy, s * r, -.7, .7)
            cr.stroke()


class MediaIsland:
    def __init__(self, app):
        self.app = app
        self.win = self.catcher = None
        self.is_open = False
        self.data = {}
        self.players = []
        self.selection = ''
        self.cap_x, self.cap_w = 330.0, 280.0
        self.marker_cap = None
        self.marker_t = 0.0
        self.locating = False
        self.L = 0.0
        _, self.screen_w, _ = barpos.screen_info()
        self.sx, self.sy = Spring(330, omega=15, zeta=.7), Spring(CAP_Y, omega=15, zeta=.7)
        self.sw, self.sh = Spring(280, omega=16, zeta=.62), Spring(CAP_H, omega=12.5, zeta=.68)
        self.ca = Spring(0, omega=18, zeta=1.0)
        self.t = 0.0
        self.open_t = 0.0
        self.pointer = None
        self.zones = []
        self.local = None
        self.press_pop = {}
        self.bands = [0.0] * 24
        self.bass = Spring(0, omega=30, zeta=.5)
        self.playing_a = Spring(0, omega=14, zeta=.8)     # 0 paused .. 1 playing (cover size, wave amplitude)
        self.pp_morph = Spring(0, omega=22, zeta=.55)     # play/pause icon morph
        self.cover_slide = Spring(1, omega=16, zeta=.8)
        self.slide_dir = 1
        self.cover = self.old_cover = None
        self.cover_url = None
        self.accent_glow = (.3, .5, .9)
        self.glow_target = self.accent_glow
        self.identity = None
        self.title_scroll = 0.0
        self.title_t0 = 0.0
        self.drag = None            # ('seek'|'vol', preview fraction)
        self.press = None
        self.preview = 0.0
        self.pending = {}
        self.chooser = Spring(0, omega=22, zeta=.9)
        self.chooser_open = False
        self.vol_pop = Spring(0, omega=26, zeta=.5)
        self.frame_tick = None
        self._fl = None
        self._busy = True
        self.region_key = None
        cmd = read(STATE / 'island-cmd.json')
        self.cmd_seq = cmd.get('seq') if isinstance(cmd, dict) else None
        self._hovered_before = False
        GLib.timeout_add(100, self._hover_watch)
        GLib.timeout_add(3000, lambda: self.locate() or False)
        GLib.timeout_add(1500, self._prewarm)
        GLib.timeout_add(50, self._poll)
        GLib.timeout_add(1000, self._beat)
        self._beat()

    # ----------------------------------------------------------------- plumbing
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
            self.close() if self.is_open else self.open()
        elif cmd == 'open':
            self.open()
        elif cmd == 'close':
            self.close()
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

    def command(self, action, value=None):
        deliver(dict(id=str(time.time_ns()), action=action, value=value, target=self.data.get('bus'),
                     sent=time.monotonic()))
        if action == 'PlayPause':
            new = not self.data.get('playing', False)
            self.data['playing'] = new
            self.pending['PlayPause'] = (new, time.monotonic())
        elif action in ('SetPosition', 'Volume'):
            self.pending[action] = (value, time.monotonic())

    # ------------------------------------------------------------ capsule position
    def locate(self):
        if self.locating:
            return
        self.locating = True

        def work():
            res = None
            try:
                st = read(STATE / 'status.json')
                mk = st.get('marker') if isinstance(st, dict) else None
                if mk:
                    res = barpos.find_marker(tuple(int(v) for v in mk), min_run=3, vchecks=(1,))
            except (OSError, ValueError, TypeError):
                pass
            GLib.idle_add(self._located, res)
        threading.Thread(target=work, daemon=True).start()

    def _located(self, res):
        self.locating = False
        self.marker_t = time.monotonic()
        if res:
            self.marker_cap = res[0] - 12.0              # marker = 4 px into the canvas, which sits ~8 px inside the capsule
            self._measure()
            if self.is_open:
                self._start_frames()
        return False

    def _hover_watch(self):
        v = read(STATE / 'input.json')
        hov = bool(v.get('hovered')) if isinstance(v, dict) else False
        if hov and not self._hovered_before and time.monotonic() - self.marker_t > 1.5:
            self.locate()
        self._hovered_before = hov
        return True

    def _measure(self):
        st = read(STATE / 'status.json')
        w = float(st.get('width', 260)) if isinstance(st, dict) else 260.0
        self.cap_w = w + 10.0
        if self.marker_cap is not None and time.monotonic() - self.marker_t < 600:
            self.cap_x = self.marker_cap

    def _target_rect(self):
        if not self.is_open:
            return self.cap_x, CAP_Y, self.cap_w, CAP_H
        x = max(10.0, min(self.screen_w - EW - 10, self.cap_x - 14))
        return x, 4.0, EW, EH

    # ------------------------------------------------------------------- open/close
    def open(self):
        if self.is_open:
            return
        self.is_open = True
        self.open_t = time.monotonic()
        self._measure()
        self.sx.snap(self.cap_x)
        self.sy.snap(CAP_Y)
        self.sw.snap(self.cap_w)
        self.sh.snap(CAP_H)
        self.ca.snap(0)
        self.chooser.snap(0)
        self.chooser_open = False
        self._ensure_windows()
        if time.monotonic() - self.marker_t > 20:
            self.locate()
        fx = self._target_rect()[0]
        self.L = max(0.0, min(fx - 40.0, self.screen_w - WIN_W))
        LS.set_margin(self.win, LS.Edge.LEFT, int(self.L))
        THEME.refresh(force=True)
        self.catcher.present()
        gfx.glass_prepare()
        self.win.present()
        self._start_frames()

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        self.drag = None
        self._start_frames()

    # ---------------------------------------------------------------- windows
    def _ensure_windows(self):
        if self.win is not None:
            return
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('mi-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.TOP)
        LS.set_namespace(catcher, 'media-island-catcher')
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
        win.add_css_class('mi-island')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'media-island')
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
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect('drag-begin', self._drag_begin)
        drag.connect('drag-update', self._drag_update)
        drag.connect('drag-end', self._drag_end)
        da.add_controller(drag)
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
        css.load_from_string('window.mi-island, window.mi-catcher { background: transparent; }')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win, self.da = win, da

    # ----------------------------------------------------------------- frames
    def _start_frames(self):
        if self.win is not None and self.frame_tick is None:
            self._fl = None
            self.frame_tick = self.da.add_tick_callback(self._frame)

    def _update_data(self, dt_):
        st = read(STATE / 'status.json')
        if st:
            self.data = (st.get('player') or {}).copy()
            self.players = st.get('players', [])
            self.selection = st.get('selection', '')
        now = time.monotonic()
        for k, (value, sent) in list(self.pending.items()):
            if now - sent > .8:
                self.pending.pop(k)
            elif k == 'SetPosition':
                self.data.update(position=value, stamp=sent)
            elif k == 'Volume':
                self.data['volume'] = value
            elif k == 'PlayPause':
                self.data['playing'] = value
        ident = (self.data.get('bus'), self.data.get('title'), self.data.get('artist'))
        url = self.data.get('art_url', '')
        if ident != self.identity:
            if self.identity is not None and self.is_open:
                self.old_cover = self.cover
                self.cover_slide.x, self.cover_slide.v, self.cover_slide.t = 0.0, 0.0, 1.0
            self.identity = ident
            self.title_t0 = time.monotonic()
        if url != self.cover_url:
            self.cover_url = url
            self.cover = cover_surface(url, int(COVER * 2)) if url else None
            g = dominant_colour(url)
            self.glow_target = g or THEME.accent
        # spectrum -> smoothed bands
        inp = read(STATE / 'input.json')
        values = inp.get('spectrum', []) if isinstance(inp, dict) else []
        live_ = bool(values) and time.time() - float(inp.get('stamp', 0)) < .5 and self.data.get('playing')
        for i in range(len(self.bands)):
            sample = float(values[min(len(values) - 1, int(i * len(values) / len(self.bands)))]) if live_ else 0.0
            tau = .07 if sample > self.bands[i] else .22
            self.bands[i] += (sample - self.bands[i]) * (1 - math.exp(-min(dt_, .05) / tau))
        bass = sum(self.bands[:4]) / 4
        self.bass.t = bass

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        gap = .0155 if self._busy else .033
        if self._fl and now - self._fl < gap:
            return GLib.SOURCE_CONTINUE
        dt_ = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        THEME.refresh()
        self.t += dt_
        self._update_data(dt_)
        tx, ty, tw, th = self._target_rect()
        self.sx.t, self.sy.t, self.sw.t, self.sh.t = tx, ty, tw, th
        closing = not self.is_open
        for sp, (zo, wo) in ((self.sx, (.7, 15.0)), (self.sy, (.7, 15.0)), (self.sw, (.62, 16.0)), (self.sh, (.68, 12.5))):
            sp.z, sp.o = (zo, wo) if not closing else (.9, wo * 1.7)
        pw = (self.sw.x - self.cap_w) / max(1.0, EW - self.cap_w)
        ph = (self.sh.x - CAP_H) / max(1.0, EH - CAP_H)
        self.ca.t = 1.0 if (self.is_open and min(pw, ph) > .8) else 0.0
        playing = bool(self.data.get('playing'))
        self.playing_a.t = 1.0 if playing else 0.0
        self.pp_morph.t = 1.0 if playing else 0.0
        self.chooser.t = 1.0 if self.chooser_open else 0.0
        self.vol_pop.t = 0.0
        busy = False
        for sp in (self.sx, self.sy, self.sw, self.sh, self.ca, self.playing_a, self.pp_morph, self.cover_slide,
                   self.chooser, self.vol_pop, self.bass) + tuple(self.press_pop.values()):
            sp.step(dt_)
            busy = busy or not sp.settled
        # glow colour eases toward the cover's colour
        self.accent_glow = tuple(lerp(self.accent_glow[i], self.glow_target[i], 1 - math.exp(-dt_ * 5)) for i in range(3))
        self._busy = busy or self.is_open
        self.da.queue_draw()
        self._update_region()
        if closing and not busy:
            self.win.set_visible(False)
            self.catcher.set_visible(False)
            self.frame_tick = None
            self.region_key = None
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
        pw = (self.sw.x - self.cap_w) / max(1.0, EW - self.cap_w)
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
        ph = clamp((self.sh.x - CAP_H) / max(1.0, EH - CAP_H))
        rad = lerp(13.5, 32.0, ph)
        sa = clamp(ph * 1.4)
        if sa > .02:
            cr.save()
            cr.translate(x, y)
            cr.scale(w / EW, h / EH)
            cr.push_group()
            gfx.shadow(cr, 0, 0, EW, EH, 32, 1.5, 10)
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
            self._content(cr)
            cr.pop_group_to_source()
            cr.paint_with_alpha(ca)
            cr.restore()

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

    # --------------------------------------------------------------- content
    def _position(self):
        d = self.data
        length = float(d.get('length', 0) or 0)
        pos = float(d.get('position', 0) or 0)
        if d.get('playing'):
            pos += max(0.0, time.monotonic() - float(d.get('stamp', time.monotonic())))
        if length > 0:
            pos = min(pos, length)
        return pos, length

    def _content(self, cr):
        th = THEME
        txt, acc = th.text, th.accent
        d = self.data
        playing = bool(d.get('playing'))
        since = time.monotonic() - self.open_t
        pa = clamp(self.playing_a.x)
        bass = clamp(self.bass.x)
        # ---- glow behind the cover (follows the cover colour, breathes with the bass)
        gc = self.accent_glow
        cx, cy = EW / 2, 62 + COVER / 2 + 4
        gr = COVER * (.78 + .16 * bass * pa + .04 * math.sin(self.t * 1.3)) * ease_back((since - .05) / .5)
        g = cairo.RadialGradient(cx, cy, COVER * .2, cx, cy, max(1.0, gr))
        g.add_color_stop_rgba(0, *gc, .45 * (.4 + .6 * pa))
        g.add_color_stop_rgba(1, *gc, 0)
        cr.set_source(g)
        cr.rectangle(0, 0, EW, EH)
        cr.fill()
        # ---- header
        mt = ease_back((since - .1) / .4)
        st = '正在播放' if playing else ('已暂停' if d else '暂无播放')
        dl(cr, gfx.text_layout(st, 12.5, True), 50, 22, (*acc, 1))
        self._equalizer(cr, 22, 36, playing)
        chooser_hot = self._zone('chooser:toggle', 'r', EW - 188, 14, 170, 30)
        rrect(cr, EW - 188, 14, 170, 30, 15)
        cr.set_source_rgba(*txt, .13 if chooser_hot else .08)
        cr.fill()
        src = ('固定 · ' if self.selection else '自动 · ') + (d.get('name') or str(d.get('bus', '')).replace('org.mpris.MediaPlayer2.', ''))
        lay = gfx.make_layout(src, 12, True, width=128, lines=1)
        dl(cr, lay, EW - 176, 20, (*txt, .9))
        cr.set_source_rgba(*txt, .5)
        cr.set_line_width(1.6)
        cr.set_line_cap(1)
        cr.move_to(EW - 36, 27)
        cr.line_to(EW - 32, 31)
        cr.line_to(EW - 28, 27)
        cr.stroke()
        # ---- cover
        self._draw_cover(cr, cx, cy, pa, bass, since)
        # ---- title / artist
        title = d.get('title') or '打开播放器开始聆听'
        self._title(cr, title, 24, 298, EW - 48, txt)
        dl(cr, gfx.make_layout(d.get('artist') or '', 14, False, width=EW - 48, lines=1), 24, 328, (*txt, .55))
        # ---- progress
        self._progress(cr, 366, playing, pa, txt, acc)
        # ---- controls
        self._controls(cr, 452, txt, acc, playing)
        # ---- volume
        self._volume(cr, 508, txt, acc)
        # ---- player chooser overlay
        if self.chooser.x > .01:
            self._chooser(cr, txt, acc)

    def _equalizer(self, cr, x, y, playing):
        th = THEME
        for i in range(3):
            if playing:
                h = 4 + 10 * (.5 + .5 * math.sin(self.t * (4.5 + i * 1.3) + i * 1.7)) * (.6 + .8 * clamp(self.bands[i * 2] * 2))
            else:
                h = 3.0
            rrect(cr, x - 8 + i * 6, y - h, 3.5, h, 1.7)
            cr.set_source_rgba(*th.accent, 1)
            cr.fill()

    def _draw_cover(self, cr, cx, cy, pa, bass, since):
        appear = ease_back((since - .08) / .5)
        size = COVER * (.9 + .1 * pa) * (1 + .035 * bass * pa) * max(.01, appear)
        slide = clamp(self.cover_slide.x)

        def paint(cover, offx, alpha, scale=1.0):
            s = size * scale
            x0, y0 = cx - s / 2 + offx, cy - s / 2
            cr.save()
            rrect(cr, x0, y0, s, s, 26 * scale)
            cr.clip()
            if cover is not None:
                cr.translate(x0, y0)
                cr.scale(s / (COVER * 2), s / (COVER * 2))
                cr.set_source_surface(cover)
                cr.paint_with_alpha(alpha * (.78 + .22 * pa))
            else:
                cr.set_source_rgba(.14, .15, .19, alpha)
                cr.paint()
                ctext(cr, '♪', 64 * scale, True, x0 + s / 2, y0 + s / 2, (*THEME.accent, alpha))
            cr.restore()
            if cover is None:
                return
            rrect(cr, x0, y0, s, s, 26 * scale)
            cr.set_source_rgba(1, 1, 1, .08 * alpha)
            cr.set_line_width(1)
            cr.stroke()
        if self.old_cover is not None and slide < .999:
            paint(self.old_cover, -slide * 70, 1 - slide, 1 - slide * .15)
        paint(self.cover, (1 - slide) * 70 * self.slide_dir, clamp(slide * 1.3), .85 + .15 * slide)
        if slide >= .999:
            self.old_cover = None

    def _title(self, cr, title, x, y, w, txt):
        lay = gfx.make_layout(title, 21, True)
        tw = gfx.text_size(lay)[0]
        if tw <= w:
            dl(cr, lay, x, y, (*txt, 1))
            return
        # long titles scroll gently
        t = self.t - (self.title_t0 - self.title_t0)
        span = tw - w + 30
        phase = (self.t * 26) % (span + 90)
        off = max(0.0, min(span, phase - 45))
        cr.save()
        cr.rectangle(x - 2, y - 4, w + 4, 34)
        cr.clip()
        gfx.draw_layout(cr, lay, x - off, y, (*txt, 1))
        cr.restore()

    def _progress(self, cr, y, playing, pa, txt, acc):
        pos, length = self._position()
        fx0, fx1 = 24.0, EW - 24.0
        frac = clamp(pos / length) if length > 0 else 0.0
        if self.drag and self.drag[0] == 'seek':
            frac = self.drag[1]
            pos = frac * length
        px = fx0 + (fx1 - fx0) * frac
        hot = self._zone('seek', 'r', fx0 - 6, y - 14, fx1 - fx0 + 12, 28)
        # unplayed: straight line
        cr.set_line_width(4)
        cr.set_line_cap(1)
        cr.set_source_rgba(*txt, .16)
        cr.move_to(px, y)
        cr.line_to(fx1, y)
        cr.stroke()
        # played: a travelling wave that calms down when paused
        amp = (2.6 + 2.2 * clamp(self.bass.x * 2)) * pa
        cr.set_source_rgba(*acc, 1)
        cr.new_path()
        n = max(2, int((px - fx0) / 3))
        for i in range(n + 1):
            xx = fx0 + (px - fx0) * i / n
            edge = min(1.0, (px - xx) / 14.0, (xx - fx0) / 10.0 + .4)
            yy = y + math.sin(xx * .16 - self.t * 6) * amp * max(0.0, edge)
            if i == 0:
                cr.move_to(xx, yy)
            else:
                cr.line_to(xx, yy)
        cr.stroke()
        # knob
        knob = 6.0 + (2.5 if (hot or self.drag) else 0)
        cr.arc(px, y, knob, 0, math.tau)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.fill()
        live(cr, clock_text(pos), 11.5, False, fx0, y + 22, (*txt, .55), left=True)
        end = clock_text(length) if length > 0 else '直播'
        lay = gfx.text_layout(end, 11.5)
        gfx.draw_layout(cr, lay, fx1 - gfx.text_size(lay)[0], y + 22 - gfx.text_size(lay)[1] / 2, (*txt, .55))

    def _controls(self, cr, y, txt, acc, playing):
        d = self.data
        specs = (('Previous', EW / 2 - 92, 24, bool(d.get('can_previous', True))),
                 ('PlayPause', EW / 2, 34, bool(d)),
                 ('Next', EW / 2 + 92, 24, bool(d.get('can_next', True))))
        for action, cx, r, enabled in specs:
            hot = self._zone('btn:' + action, 'c', cx, y, r + 4)
            s = self._pop('btn:' + action) * (1.05 if hot and enabled else 1.0)
            cr.save()
            cr.translate(cx, y)
            cr.scale(s, s)
            cr.arc(0, 0, r, 0, math.tau)
            if action == 'PlayPause':
                gg = cairo.LinearGradient(0, -r, 0, r)
                gg.add_color_stop_rgb(0, *[min(1, v + .12) for v in acc])
                gg.add_color_stop_rgb(1, *[v * .86 for v in acc])
                cr.set_source(gg)
            else:
                cr.set_source_rgba(*txt, .16 if (hot and enabled) else .08)
            cr.fill()
            col = (1, 1, 1, 1) if action == 'PlayPause' else (*txt, 1.0 if enabled else .3)
            if action == 'PlayPause':
                icon_playpause(cr, 0, 0, 24, col, self.pp_morph.x)
            elif action == 'Previous':
                icon_prev(cr, 0, 0, 20, col)
            else:
                icon_next(cr, 0, 0, 20, col)
            cr.restore()

    def _volume(self, cr, y, txt, acc):
        vol = self.data.get('volume')
        x0, x1 = 58.0, EW - 56.0
        if vol is None:
            dl(cr, gfx.text_layout('播放器不支持调节音量', 11.5), 24, y - 8, (*txt, .4))
            return
        v = clamp(self.drag[1]) if (self.drag and self.drag[0] == 'vol') else clamp(float(vol))
        hot = self._zone('vol', 'r', x0 - 8, y - 14, x1 - x0 + 16, 28)
        icon_speaker(cr, 34, y, 15, (*txt, .75), v)
        cr.set_line_width(4)
        cr.set_line_cap(1)
        cr.set_source_rgba(*txt, .16)
        cr.move_to(x0, y)
        cr.line_to(x1, y)
        cr.stroke()
        px = x0 + (x1 - x0) * v
        cr.set_source_rgba(*acc, 1)
        cr.move_to(x0, y)
        cr.line_to(px, y)
        cr.stroke()
        cr.arc(px, y, 5.5 + (2 if (hot or self.drag) else 0), 0, math.tau)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.fill()
        live(cr, str(round(v * 100)), 11.5, False, EW - 24, y, (*txt, .55))

    def _chooser(self, cr, txt, acc):
        p = clamp(self.chooser.x)
        cr.save()
        # dim the player behind
        cr.set_source_rgba(0, 0, 0, .6 * p)
        cr.rectangle(0, 0, EW, EH)
        cr.fill()
        self.zones.append(('chooser:close', 'r', (0.0, 0.0, EW, EH)))
        cr.translate(0, -10 * (1 - p))
        cr.push_group()
        rows = self.players[:6]
        h = 96 + 50 * len(rows) + 50
        rrect(cr, 16, 56, EW - 32, h, 22)
        cr.set_source_rgba(.1, .11, .14, 1)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, .08)
        cr.set_line_width(1)
        cr.stroke()
        dl(cr, gfx.text_layout('选择播放器', 16, True), 34, 70, (*txt, 1))
        y = 106.0
        auto_hot = self._zone('chooser:select:', 'r', 26, y, EW - 52, 44)
        rrect(cr, 26, y, EW - 52, 44, 13)
        cr.set_source_rgba(*(acc if not self.selection else txt), .24 if not self.selection else (.12 if auto_hot else .06))
        cr.fill()
        dl(cr, gfx.text_layout('自动选择', 13, True), 40, y + 6, (*txt, 1))
        dl(cr, gfx.text_layout('优先播放中，保持当前来源', 10.5), 40, y + 25, (*txt, .5))
        y += 52
        for item in rows:
            chosen = self.selection == item.get('bus')
            hot = self._zone('chooser:select:' + str(item.get('bus')), 'r', 26, y, EW - 52, 44)
            rrect(cr, 26, y, EW - 52, 44, 13)
            cr.set_source_rgba(*(acc if chosen else txt), .24 if chosen else (.12 if hot else .06))
            cr.fill()
            name = item.get('name') or str(item.get('bus', '')).replace('org.mpris.MediaPlayer2.', '')
            dl(cr, gfx.make_layout(name, 13, True, width=200, lines=1), 40, y + 6, (*txt, 1))
            state = '播放中' if item.get('playing') else ('已暂停' if item.get('status') == 'Paused' else '已停止')
            sl = gfx.text_layout(state, 10.5)
            dl(cr, sl, EW - 40 - gfx.text_size(sl)[0], y + 8, (*(acc if item.get('playing') else txt), .8))
            dl(cr, gfx.make_layout(item.get('title') or '暂无曲目', 10.5, False, width=300, lines=1), 40, y + 25, (*txt, .5))
            y += 50
        cr.pop_group_to_source()
        cr.paint_with_alpha(p)
        cr.restore()

    # ----------------------------------------------------------------- input
    def _on_motion(self, ctl, x, y):
        self.pointer = (x + self.L, y)
        self._start_frames()

    def _on_leave(self, ctl):
        self.pointer = None
        self._start_frames()

    def _local(self, x, y):
        bx, by, _, _ = self._rect()
        return x + self.L - bx, y - by

    def _hit(self, p):
        for key, shape, a in reversed(self.zones):
            if self._inside(shape, a, p):
                return key
        return None

    def _fraction(self, key, px):
        if key == 'seek':
            return clamp((px - 24.0) / (EW - 48.0))
        return clamp((px - 58.0) / (EW - 114.0))

    def _drag_begin(self, g, x, y):
        p = self._local(x, y)
        self.press = (p, self._hit(p))
        key = self.press[1]
        if key == 'seek' and float(self.data.get('length', 0) or 0) > 0 and self.data.get('can_seek', True):
            self.drag = ('seek', self._fraction('seek', p[0]))
        elif key == 'vol' and self.data.get('volume') is not None:
            self.drag = ('vol', self._fraction('vol', p[0]))
        self._start_frames()

    def _drag_update(self, g, dx, dy):
        if self.drag and self.press:
            px = self.press[0][0] + dx
            self.drag = (self.drag[0], self._fraction(self.drag[0], px))
            if self.drag[0] == 'vol':
                self.command('Volume', self.drag[1])
            self._start_frames()

    def _drag_end(self, g, dx, dy):
        press, self.press = self.press, None
        d, self.drag = self.drag, None
        if press is None:
            return
        if d:
            if d[0] == 'seek':
                self.command('SetPosition', d[1] * float(self.data.get('length', 0) or 0))
            else:
                self.command('Volume', d[1])
        elif abs(dx) < 8 and abs(dy) < 8 and press[1]:
            self._act(press[1])
        self._start_frames()

    def _act(self, key):
        if key.startswith('btn:'):
            action = key[4:]
            self._press(key)
            if action in ('Next', 'Previous'):
                self.slide_dir = 1 if action == 'Next' else -1
            self.command(action)
        elif key == 'chooser:toggle':
            self.chooser_open = not self.chooser_open
        elif key == 'chooser:close':
            self.chooser_open = False
        elif key.startswith('chooser:select:'):
            sel = key[len('chooser:select:'):]
            self.command('SelectPlayer', sel)
            self.selection = sel
            self.chooser_open = False

    def _on_scroll(self, ctl, dx, dy):
        if not self.is_open or abs(dy) < .01 or self.data.get('volume') is None:
            return True
        v = clamp(float(self.data.get('volume', 0)) - dy * .03)
        self.command('Volume', v)
        self._start_frames()
        return True

    def _on_key(self, ctl, keyval, keycode, state):
        name = Gdk.keyval_name(keyval)
        if name == 'Escape':
            if self.chooser_open:
                self.chooser_open = False
            else:
                self.close()
        elif name == 'space':
            self._act('btn:PlayPause')
        elif name == 'Right':
            self._act('btn:Next')
        elif name == 'Left':
            self._act('btn:Previous')
        elif name == 'Up':
            self._on_scroll(None, 0, -1)
        elif name == 'Down':
            self._on_scroll(None, 0, 1)
        else:
            return False
        self._start_frames()
        return True


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    lock = open(STATE / 'island.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    app = Gtk.Application(application_id='dev.pr.MediaIsland', flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def on_activate(a):
        a.hold()
        holder['island'] = MediaIsland(a)

    app.connect('activate', on_activate)
    app.run([])


if __name__ == '__main__':
    main()

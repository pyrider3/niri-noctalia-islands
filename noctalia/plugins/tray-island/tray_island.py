#!/usr/bin/env python3
"""Tray island: the bar's chevron grows into a black island holding the system tray icons.

Acts as an extra StatusNotifier host (Noctalia owns the watcher): left click activates an app, right click shows
the app's own menu (com.canonical.dbusmenu) inside the island, middle click does the secondary action.
Commands arrive in ~/.local/state/tray-island/island-cmd.json ({"cmd": "toggle"|"open"|"close", "seq": n}).
"""
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
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

import barpos  # noqa: E402
import gfx  # noqa: E402
from clock_island import dl  # noqa: E402
from gfx import THEME, Spring, clamp, lerp, rrect  # noqa: E402

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'tray-island'
CMD, ALIVE = STATE / 'island-cmd.json', STATE / 'island-alive.json'
WATCHER = ('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher')
SNI = 'org.kde.StatusNotifierItem'
BLACK = (.016, .016, .022)
SHADOW = 34
CELL, PAD, LABEL_H = 40.0, 8.0, 20.0
ICON = 22.0
CHEV_X = 9.0                     # chevron centre inside the bar capsule (see tray_canvas.py)
MENU_W, ROW_H, SEP_H, MENU_MAX_H = 190.0, 26.0, 10.0, 340.0
HIDE_IDS = ('fcitx',)            # the input-method indicator lives in the bar capsule


def read_json(p):
    try:
        v = json.loads(Path(p).read_text())
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


class Bus:
    """Blocking D-Bus helpers; always called from worker threads."""

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(self, name, path, iface, method, params=None, reply=None, timeout=450):
        try:
            res = self.bus.call_sync(name, path, iface, method, params, GLib.VariantType(reply) if reply else None,
                                     Gio.DBusCallFlags.NONE, timeout, None)
            return res.unpack() if res is not None else None
        except GLib.Error:
            return None

    def items(self):
        r = self.call(WATCHER[0], WATCHER[1], 'org.freedesktop.DBus.Properties', 'Get',
                      GLib.Variant('(ss)', (WATCHER[0], 'RegisteredStatusNotifierItems')), '(v)')
        out = []
        for entry in (r[0] if r else []):
            bus, _, path = str(entry).partition('/')
            out.append((bus, '/' + path))
        return out

    def props(self, bus, path):
        r = self.call(bus, path, 'org.freedesktop.DBus.Properties', 'GetAll', GLib.Variant('(s)', (SNI,)), '(a{sv})')
        return r[0] if r else None


def pixmap_surface(pix):
    """IconPixmap a(iiay): pick the largest, convert network-order ARGB to cairo's premultiplied BGRA."""
    best = max(pix, key=lambda p: p[0] * p[1])
    w, h, data = best
    data = bytes(data)
    if w <= 0 or h <= 0 or len(data) < w * h * 4:
        return None
    out = bytearray(w * h * 4)
    for i in range(0, w * h * 4, 4):
        a, r, g, b = data[i], data[i + 1], data[i + 2], data[i + 3]
        out[i], out[i + 1], out[i + 2], out[i + 3] = b * a // 255, g * a // 255, r * a // 255, a
    return cairo.ImageSurface.create_for_data(out, cairo.FORMAT_ARGB32, w, h, w * 4)


def pixbuf_surface(pb):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pb.get_width(), pb.get_height())
    c = cairo.Context(surf)
    Gdk.cairo_set_source_pixbuf(c, pb, 0, 0)
    c.paint()
    return surf


class Island:
    def __init__(self, app):
        self.app = app
        self.dbus = Bus()
        self.is_open = False
        self.t = 0.0
        self.items = []
        self.icons = {}
        self.pages = []                    # menu pages: [{'title','rows','item'}]
        self.menu_scroll = Spring(0, omega=20, zeta=.95)
        self.menu_t = 0.0
        self.sx = Spring(0, omega=17, zeta=.74)
        self.sy = Spring(4, omega=17, zeta=.74)
        self.sw = Spring(24, omega=17, zeta=.72)
        self.sh = Spring(20, omega=15, zeta=.72)
        self.ca = Spring(0, omega=18, zeta=1.0)
        self.page_f = Spring(1, omega=22, zeta=.9)
        self.hov, self.press = {}, {}
        self.local = None
        self.zones = []
        self.frame_tick = None
        self._fl = None
        self.region_key = None
        self.cmd_seq = read_json(CMD).get('seq')
        self.screen_w = 1755.0
        self.cap_left = None               # located capsule left edge (logical px)
        self.cap_t = 0.0
        self.locating = False
        self.chev = 0.0
        self.label = ''
        self.hover_key = None
        self._build()
        for member in ('StatusNotifierItemRegistered', 'StatusNotifierItemUnregistered'):
            self.dbus.bus.signal_subscribe(None, WATCHER[0], member, WATCHER[1], None, Gio.DBusSignalFlags.NONE,
                                           lambda *a: GLib.idle_add(self.refresh))
        self.refresh()
        GLib.timeout_add(90, self._poll_cmd)
        GLib.timeout_add(1000, self._beat)
        GLib.timeout_add_seconds(30, self._relocate)
        self._beat()
        GLib.timeout_add(1500, lambda: self.locate() or False)

    # --------------------------------------------------------------- windows
    def _build(self):
        css = Gtk.CssProvider()
        css.load_from_string('window.tr-win, window.tr-catcher { background: transparent; }')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('tr-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.TOP)
        LS.set_namespace(catcher, 'tray-island-catcher')
        for e in (LS.Edge.TOP, LS.Edge.RIGHT, LS.Edge.BOTTOM, LS.Edge.LEFT):
            LS.set_anchor(catcher, e, True)
        LS.set_exclusive_zone(catcher, -1)
        LS.set_keyboard_mode(catcher, LS.KeyboardMode.NONE)
        blank = Gtk.Box(hexpand=True, vexpand=True)
        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect('pressed', lambda g, n, x, y: self.close())
        blank.add_controller(click)
        catcher.set_child(blank)
        self.catcher = catcher
        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('tr-win')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'tray-island')
        LS.set_exclusive_zone(win, -1)
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_anchor(win, LS.Edge.RIGHT, True)       # as wide as the screen: the island moves inside it
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        self.win_h = 520
        win.set_default_size(100, self.win_h)
        da = Gtk.DrawingArea()
        da.set_hexpand(True)
        da.set_content_height(self.win_h)
        da.set_draw_func(self.draw)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', lambda c, x, y: self._motion(x, y))
        motion.connect('leave', lambda c: self._motion(None, None))
        da.add_controller(motion)
        for button in (1, 2, 3):
            g = Gtk.GestureClick()
            g.set_button(button)
            g.connect('pressed', lambda gg, n, x, y, b=button: self._on_press(b, x, y))
            da.add_controller(g)
        wheel = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        wheel.connect('scroll', self._on_wheel)
        da.add_controller(wheel)
        win.set_child(da)
        self.win, self.da = win, da

    def _beat(self):
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            tmp = ALIVE.with_suffix('.tmp')
            tmp.write_text(json.dumps({'t': time.time(), 'open': self.is_open}))
            os.replace(tmp, ALIVE)
        except OSError:
            pass
        return True

    def _poll_cmd(self):
        d = read_json(CMD)
        if d.get('seq') is not None and d['seq'] != self.cmd_seq:
            self.cmd_seq = d['seq']
            cmd = d.get('cmd', 'toggle')
            if cmd == 'close' or (cmd == 'toggle' and self.is_open):
                self.close()
            else:
                self.open()
        return True

    # ------------------------------------------------------------- locating
    def locate(self):
        if self.locating:
            return
        self.locating = True

        def work():
            res = None
            try:
                st = read_json(STATE / 'status.json')
                mk, mx = st.get('marker'), st.get('marker_x')
                if mk and mx is not None:
                    r = barpos.find_marker(tuple(int(v) for v in mk), min_run=3)
                    if r:
                        res = r[0] - float(mx), r[2]
            except (OSError, ValueError, TypeError):
                pass
            GLib.idle_add(self._located, res)
        threading.Thread(target=work, daemon=True).start()

    def _located(self, res):
        self.locating = False
        self.cap_t = time.monotonic()
        if res:
            self.cap_left, self.screen_w = res
        return False

    def _relocate(self):
        if not self.is_open and self.sw.x <= 28:
            self.locate()
        return True

    def chevron_x(self):
        left = self.cap_left if self.cap_left is not None else self.screen_w - 330.0
        return left + CHEV_X

    # ----------------------------------------------------------- open/close
    def open(self):
        if self.is_open:
            return
        cx = self.chevron_x()          # located while closed (the open island would hide the marker)
        live = set(self.dbus.items())    # one quick call: drop apps that already quit before drawing anything
        self.items = [i for i in self.items if (i['bus'], i['path']) in live]
        self.is_open = True
        self.pages = []
        self.hover_key = None
        self.sx.snap(cx - 12)
        self.sy.snap(5)
        self.sw.snap(24)
        self.sh.snap(20)
        self.ca.snap(0)
        self.page_f.snap(1)
        self.refresh()
        LS.set_margin(self.win, LS.Edge.LEFT, 0)
        LS.set_margin(self.win, LS.Edge.TOP, 0)
        THEME.refresh(force=True)
        self.catcher.set_visible(True)
        self.catcher.present()
        self.win.present()
        self.start_frames()
        GLib.timeout_add(1500, self._refresh_loop)

    def close(self):
        if self.is_open:
            self.is_open = False
            self.start_frames()

    def _refresh_loop(self):
        if self.is_open and not self.pages:
            self.refresh()
        return self.is_open

    # ----------------------------------------------------------------- data
    def refresh(self):
        def work():
            items = []
            for bus, path in self.dbus.items():
                p = self.dbus.props(bus, path)
                if not p:
                    continue
                ident = str(p.get('Id', ''))
                if any(h in ident.lower() or h in str(p.get('Title', '')).lower() for h in HIDE_IDS):
                    continue
                items.append(dict(bus=bus, path=path, id=ident, title=self._pretty(str(p.get('Title') or ident or bus)),
                                  status=str(p.get('Status', 'Active')), props=p))
            GLib.idle_add(self._set_items, items)
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _pretty(name):
        import re
        name = re.sub(r'[_-]?status[_-]?icon[_-]?\d*$', '', name, flags=re.I).strip('_- ')
        return (name or 'App').replace('_', ' ')

    def _set_items(self, items):
        keep = {(i['bus'], i['path']) for i in items}
        for it in items:
            key = (it['bus'], it['path'])
            if key not in self.icons:
                self.icons[key] = self._load_icon(it['props'])
        for k in list(self.icons):
            if k not in keep:
                del self.icons[k]
        order = {k: n for n, k in enumerate((i['bus'], i['path']) for i in self.items)}
        items.sort(key=lambda i: order.get((i['bus'], i['path']), 999))
        self.items = items
        self.loaded = True
        self.start_frames()
        return False

    def _load_icon(self, p):
        pix = p.get('IconPixmap')
        if pix:
            try:
                s = pixmap_surface(pix)
                if s is not None:
                    return s
            except (ValueError, TypeError):
                pass
        name = str(p.get('IconName') or '')
        if name:
            try:
                if name.startswith('/') and os.path.exists(name):
                    return pixbuf_surface(GdkPixbuf.Pixbuf.new_from_file_at_size(name, 96, 96))
                theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
                tp = str(p.get('IconThemePath') or '')
                if tp and tp not in theme.get_search_path():
                    theme.add_search_path(tp)
                ic = theme.lookup_icon(name, None, 64, 2, Gtk.TextDirection.NONE, 0)
                f = ic.get_file() if ic else None
                if f is not None and f.get_path():
                    return pixbuf_surface(GdkPixbuf.Pixbuf.new_from_file_at_size(f.get_path(), 96, 96))
            except (GLib.Error, TypeError):
                pass
        return None

    # --------------------------------------------------------------- layout
    def grid(self):
        n = max(1, len(self.items))
        cols = max(3, min(5, math.ceil(n / 2))) if n > 3 else n      # 6 icons: 3 x 2
        rows = math.ceil(n / cols)
        return cols, rows

    @staticmethod
    def rows_height(rows):
        return sum(SEP_H if r.get('sep') else ROW_H for r in rows)

    def menu_view_h(self):
        return min(MENU_MAX_H, self.rows_height(self.pages[-1]['rows']))

    def target_size(self):
        if self.pages:
            return MENU_W, 36 + self.menu_view_h() + 6
        cols, rows = self.grid()
        return cols * CELL + 2 * PAD, rows * CELL + 2 * PAD + LABEL_H

    # ---------------------------------------------------------------- frames
    def start_frames(self):
        if self.frame_tick is None:
            self._fl = None
            self.frame_tick = self.da.add_tick_callback(self._frame)

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        if self._fl and now - self._fl < .0155:
            return GLib.SOURCE_CONTINUE
        dt = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        self.t += dt
        THEME.refresh()
        cx = self.chevron_x()
        if self.is_open:
            w, h = self.target_size()
            x = max(10.0, min(self.screen_w - w - 10, cx - w / 2))
            self.sx.t, self.sy.t, self.sw.t, self.sh.t = x, 6.0, w, h
            for sp, (z, o) in ((self.sx, (.74, 17.0)), (self.sy, (.74, 17.0)), (self.sw, (.72, 17.0)), (self.sh, (.72, 14.0))):
                sp.z, sp.o = z, o
        else:
            self.sx.t, self.sy.t, self.sw.t, self.sh.t = cx - 12, 5.0, 24.0, 20.0
            for sp in (self.sx, self.sy, self.sw, self.sh):
                sp.z, sp.o = 1.0, 30.0
        full_w, full_h = self.target_size()
        self.ca.t = 1.0 if (self.is_open and self.sw.x > full_w * .82 and self.sh.x > min(full_h, 90) * .8) else 0.0
        self.page_f.t = 1.0
        busy = False
        self.menu_scroll.t = self.menu_t
        for sp in [self.sx, self.sy, self.sw, self.sh, self.ca, self.page_f, self.menu_scroll] + list(self.hov.values()) + list(self.press.values()):
            sp.step(dt)
            busy = busy or not sp.settled
        self._update_region()
        self.da.queue_draw()
        if not self.is_open and self.sw.x <= 28:
            self.win.set_visible(False)
            self.catcher.set_visible(False)
            self.region_key = None
            self.frame_tick = None
            return GLib.SOURCE_REMOVE
        if self.is_open and not busy:         # settled: stop redrawing until the pointer or the data changes
            self.frame_tick = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _rect(self):
        return self.sx.x, self.sy.x, max(8.0, self.sw.x), max(8.0, self.sh.x)

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        key = None
        if self.is_open or self.sw.x > 28:
            x, y, w, h = self._rect()
            key = (int(x), int(y), int(w), int(h))
        if key == self.region_key:
            return
        self.region_key = key
        surface.set_input_region(cairo.Region([cairo.RectangleInt(*key)]) if key else cairo.Region())

    # ------------------------------------------------------------- drawing
    def draw(self, area, cr, W, H):
        try:
            self._draw(cr)
        except Exception:
            import traceback
            try:
                (STATE / 'island-error.txt').write_text(traceback.format_exc())
            except OSError:
                pass

    def _sp(self, store, key, omega=24, zeta=.7):
        sp = store.get(key)
        if sp is None:
            sp = store[key] = Spring(0, omega=omega, zeta=zeta)
        return sp

    def _hot(self, key, x, y, w, h):
        self.zones.append((key, x, y, w, h))
        p = self.local
        return p is not None and x <= p[0] <= x + w and y <= p[1] <= y + h

    def _draw(self, cr):
        x, y, w, h = self._rect()
        full_w, _ = self.target_size()
        ga = 1.0 if self.is_open else clamp((self.sw.x - 24) / 60.0)
        if ga < .01:
            return
        cr.push_group()
        txt, acc = THEME.text, THEME.accent
        self.zones = []
        r = min(18, h / 2, w / 2)
        gfx.shadow(cr, x, y, w, h, r, 1.4, 8)
        rrect(cr, x, y, w, h, r)
        cr.set_source_rgb(*BLACK)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, .09)
        cr.set_line_width(1)
        cr.stroke()
        a = clamp(self.ca.x)
        if a > .02:
            cr.save()
            rrect(cr, x, y, w, h, r)
            cr.clip()
            cr.translate(x, y)
            self.local_p = None if self.local is None else (self.local[0] - x, self.local[1] - y)
            saved, self.local = self.local, self.local_p
            cr.push_group()
            if self.pages:
                self._draw_menu(cr, w, h, txt, acc)
            else:
                self._draw_grid(cr, w, h, txt, acc)
            cr.pop_group_to_source()
            cr.paint_with_alpha(a)
            self.local = saved
            cr.restore()
        cr.pop_group_to_source()
        cr.paint_with_alpha(ga)

    def _draw_grid(self, cr, w, h, txt, acc):
        cols, _ = self.grid()
        hovered = None
        for n, it in enumerate(self.items):
            col, row = n % cols, n // cols
            x0, y0 = PAD + col * CELL, PAD + row * CELL
            key = ('item', n)
            hot = self._hot(key, x0, y0, CELL, CELL)
            sp = self._sp(self.hov, key)
            sp.t = 1.0 if hot else 0.0
            ps = self._sp(self.press, key, 30, .55)
            if hot:
                hovered = it
            cx, cy = x0 + CELL / 2, y0 + CELL / 2
            cr.save()
            cr.translate(cx, cy)
            s = 1 + .08 * sp.x - .12 * ps.x
            cr.scale(s, s)
            rrect(cr, -CELL / 2 + 2, -CELL / 2 + 2, CELL - 4, CELL - 4, 12)
            cr.set_source_rgba(*txt, .06 + .1 * sp.x)
            cr.fill()
            surf = self.icons.get((it['bus'], it['path']))
            if surf is not None:
                k = ICON / max(surf.get_width(), surf.get_height())
                cr.save()
                cr.scale(k, k)
                cr.set_source_surface(surf, -surf.get_width() / 2, -surf.get_height() / 2)
                cr.paint()
                cr.restore()
            else:
                lay = gfx.text_layout((it['title'] or '?')[:1].upper(), 18, True)
                lw, lh = gfx.text_size(lay)
                dl(cr, lay, -lw / 2, -lh / 2, (*txt, .9))
            if it['status'] == 'NeedsAttention':
                cr.arc(CELL / 2 - 9, -CELL / 2 + 9, 3.4, 0, math.tau)
                cr.set_source_rgba(1.0, .55, .36, 1)
                cr.fill()
            cr.restore()
        if not self.items and getattr(self, 'loaded', False):
            lay = gfx.text_layout('没有托盘图标', 13)
            lw, _ = gfx.text_size(lay)
            dl(cr, lay, (w - lw) / 2, PAD + 20, (*txt, .4))
        # the hovered app's name
        target = hovered['title'] if hovered else ''
        if target != self.label:
            self.label = target
        lay = gfx.make_layout(self.label or ' ', 11, True, width=w - 2 * PAD, lines=1)
        lw, lh = gfx.text_size(lay)
        dl(cr, lay, (w - lw) / 2, h - LABEL_H + (LABEL_H - lh) / 2 - 4, (*txt, .7))

    def _draw_menu(self, cr, w, h, txt, acc):
        page = self.pages[-1]
        back = self._hot('back', 5, 4, w - 10, 26)
        rrect(cr, 5, 4, w - 10, 26, 11)
        cr.set_source_rgba(*txt, .12 if back else .05)
        cr.fill()
        cr.set_source_rgba(*txt, .9)
        cr.set_line_width(1.8)
        cr.set_line_cap(1)
        cr.move_to(19, 12)
        cr.line_to(14.5, 17)
        cr.line_to(19, 22)
        cr.stroke()
        dl(cr, gfx.make_layout(page['title'], 12, True, width=w - 60, lines=1), 28, 9.5, (*txt, 1))
        top, view = 36.0, self.menu_view_h()
        total = self.rows_height(page['rows'])
        limit = max(0.0, total - view)
        self.menu_t = max(0.0, min(self.menu_t, limit))
        off = max(-10.0, min(self.menu_scroll.x, limit + 10.0)) if limit else 0.0
        cr.save()
        cr.rectangle(0, top, w, view)
        cr.clip()
        y = top - off
        for i, row in enumerate(page['rows']):
            if row.get('sep'):
                cr.set_source_rgba(*txt, .1)
                cr.rectangle(14, y + SEP_H / 2, w - 28, 1)
                cr.fill()
                y += SEP_H
                continue
            if y + ROW_H < top or y > top + view:
                y += ROW_H
                continue
            enabled = row.get('enabled', True)
            zt, zb = max(y, top), min(y + ROW_H - 2, top + view)
            hot = enabled and zb > zt and self._hot(('row', i), 5, zt, w - 10, zb - zt)
            sp = self._sp(self.hov, ('row', i))
            sp.t = 1.0 if hot else 0.0
            if sp.x > .01:
                rrect(cr, 5, y, w - 10, ROW_H - 2, 9)
                cr.set_source_rgba(*acc, .22 * sp.x)
                cr.fill()
            if row.get('check'):
                cr.set_source_rgba(*acc, 1)
                cr.set_line_width(1.8)
                cr.move_to(15, y + 14)
                cr.line_to(18.5, y + 17.5)
                cr.line_to(24, y + 10.5)
                cr.stroke()
            lab = gfx.make_layout(row['label'], 11.5, False, width=w - 54, lines=1)
            dl(cr, lab, 26, y + (ROW_H - 2 - gfx.text_size(lab)[1]) / 2, (*txt, .95 if enabled else .35))
            if row.get('children'):
                cr.set_source_rgba(*txt, .6)
                cr.set_line_width(1.6)
                cr.move_to(w - 22, y + 9)
                cr.line_to(w - 17, y + 13)
                cr.line_to(w - 22, y + 17)
                cr.stroke()
            y += ROW_H
        cr.restore()
        if limit > 0:                         # scroll indicator
            th = max(18.0, view * view / total)
            ty = top + (view - th) * (off / limit)
            rrect(cr, w - 6, ty, 2.5, th, 1.25)
            cr.set_source_rgba(*txt, .25)
            cr.fill()

    # ---------------------------------------------------------------- input
    def _motion(self, x, y):
        self.local = None if x is None else (x, y)
        self.start_frames()

    def _on_wheel(self, ctl, dx, dy):
        if self.is_open and self.pages:
            self.menu_t += dy * 34
            self.start_frames()
        return True

    def _on_press(self, button, x, y):
        if not self.is_open:
            return
        rx, ry, _, _ = self._rect()
        px, py = x - rx, y - ry
        for key, zx, zy, zw, zh in reversed(self.zones):
            if zx <= px <= zx + zw and zy <= py <= zy + zh:
                if button == 3 and key != 'back' and key[0] == 'row':
                    break                      # right click on a menu row: treated like blank space below
                self._act(key, button, x, y)
                return self.start_frames()
        if button == 3:                        # right click on empty island space: back out of a menu, else close
            if self.pages:
                self.pages.pop()
            else:
                self.close()
        self.start_frames()

    def _act(self, key, button, x, y):
        if key == 'back':
            self.pages.pop()
            self.menu_t = 0.0
            self.menu_scroll.snap(0)
            return
        if key[0] == 'item':
            it = self.items[key[1]]
            sp = self._sp(self.press, key, 30, .55)
            sp.x, sp.t = 1.0, 0.0
            cx, cy = int(self.chevron_x()), 30
            if button == 1:
                self._call(it, 'Activate', cx, cy)
                GLib.timeout_add(140, lambda: self.close() or False)
            elif button == 2:
                self._call(it, 'SecondaryActivate', cx, cy)
                GLib.timeout_add(140, lambda: self.close() or False)
            else:
                self._open_menu(it, cx, cy)
        elif key[0] == 'row':
            row = self.pages[-1]['rows'][key[1]]
            if row.get('children'):
                self.menu_t = 0.0
                self.menu_scroll.snap(0)
                self.pages.append(dict(title=row['label'], rows=row['children'], item=self.pages[-1]['item'], menu=self.pages[-1].get('menu')))
            else:
                it = self.pages[-1]['item']
                self._menu_event(it, row['id'])
                GLib.timeout_add(120, lambda: self.close() or False)

    def _call(self, it, method, x, y):
        threading.Thread(target=lambda: self.dbus.call(it['bus'], it['path'], SNI, method, GLib.Variant('(ii)', (x, y))),
                         daemon=True).start()

    # ------------------------------------------------------------ dbusmenu
    def _open_menu(self, it, x, y):
        menu = it['props'].get('Menu')

        def work():
            rows = None
            if menu and str(menu) != '/':
                rows = self._fetch_menu(it['bus'], str(menu))
            if rows:
                GLib.idle_add(self._push_menu, it, rows)
            else:
                self.dbus.call(it['bus'], it['path'], SNI, 'ContextMenu', GLib.Variant('(ii)', (x, y)))
                GLib.idle_add(self.close)
        threading.Thread(target=work, daemon=True).start()

    def _push_menu(self, it, rows):
        self.menu_t = 0.0
        self.menu_scroll.snap(0)
        self.pages.append(dict(title=it['title'], rows=rows, item=it, menu=str(it['props'].get('Menu'))))
        self.start_frames()
        return False

    def _fetch_menu(self, bus, path):
        iface = 'com.canonical.dbusmenu'
        self.dbus.call(bus, path, iface, 'AboutToShow', GLib.Variant('(i)', (0,)), '(b)')
        r = self.dbus.call(bus, path, iface, 'GetLayout', GLib.Variant('(iias)', (0, -1, [])), '(u(ia{sv}av))')
        if not r:
            return None
        return self._parse(r[1][2])

    def _parse(self, children):
        rows = []
        for ch in children:
            cid, props, sub = ch
            if props.get('visible', True) is False:
                continue
            if props.get('type') == 'separator':
                rows.append({'sep': True})
                continue
            label = str(props.get('label', '')).replace('__', '\0').replace('_', '').replace('\0', '_')
            row = {'id': int(cid), 'label': label or ' ', 'enabled': props.get('enabled', True) is not False}
            if props.get('toggle-type') and props.get('toggle-state') == 1:
                row['check'] = True
            kids = self._parse(sub) if sub else None
            if kids:
                row['children'] = kids
            rows.append(row)
        return rows

    def _menu_event(self, it, mid):
        menu = None
        for pg in self.pages:
            menu = pg.get('menu') or menu
        if not menu:
            return
        stamp = int(time.time()) & 0xffffffff

        def work():
            self.dbus.call(it['bus'], menu, 'com.canonical.dbusmenu', 'Event',
                           GLib.Variant('(isvu)', (mid, 'clicked', GLib.Variant('i', 0), stamp)))
        threading.Thread(target=work, daemon=True).start()


def main():
    app = Gtk.Application(application_id='dev.pr.TrayIsland', flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def on_activate(a):
        if holder.get('i') is None:
            a.hold()
            holder['i'] = Island(a)

    app.connect('activate', on_activate)
    app.run([])


if __name__ == '__main__':
    main()

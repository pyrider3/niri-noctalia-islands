#!/usr/bin/env python3
"""Desktop settings, in the same visual language as the islands: black, springy, cairo-drawn.

A centered layer-shell window with a sidebar of categories and animated pages; opens/closes with a spring.
"""
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
sys.path.insert(0, str(HERE.parent / 'noctalia/plugins/clock-island'))
sys.path.insert(0, str(Path.home() / '.config/notifd'))

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

import ds_pages  # noqa: E402
import gfx  # noqa: E402
from clock_island import dl, ease_back  # noqa: E402
from ds_ui import PAD, Group, Ui  # noqa: E402
from gfx import THEME, Spring, clamp, lerp, rrect  # noqa: E402

PW, PH = 980.0, 660.0
SIDE_W = 236.0
CX0 = SIDE_W + 24
CW = PW - CX0 - 28
VIEW_TOP, VIEW_BOT = 92.0, PH - 14.0
PAD_WIN = 30                       # room around the panel for its shadow
BLACK = (.016, .016, .022)


def draw_icon(cr, name, cx, cy, s, col):
    cr.save()
    cr.translate(cx, cy)
    cr.set_source_rgba(*col)
    cr.set_line_width(1.6)
    cr.set_line_cap(1)
    cr.set_line_join(1)
    if name == 'image':
        rrect(cr, -s * .5, -s * .4, s, s * .8, s * .12)
        cr.stroke()
        cr.arc(-s * .18, -s * .12, s * .09, 0, math.tau)
        cr.fill()
        cr.move_to(-s * .5, s * .28)
        cr.line_to(-s * .15, s * .02)
        cr.line_to(s * .12, s * .24)
        cr.line_to(s * .26, s * .12)
        cr.line_to(s * .5, s * .32)
        cr.stroke()
    elif name == 'bell':
        cr.move_to(-s * .42, s * .3)
        cr.curve_to(-s * .28, s * .22, -s * .24, s * .06, -s * .24, -s * .12)
        cr.curve_to(-s * .24, -s * .34, -s * .12, -s * .44, 0, -s * .44)
        cr.curve_to(s * .12, -s * .44, s * .24, -s * .34, s * .24, -s * .12)
        cr.curve_to(s * .24, s * .06, s * .28, s * .22, s * .42, s * .3)
        cr.close_path()
        cr.stroke()
        cr.arc(0, s * .44, s * .07, 0, math.tau)
        cr.fill()
    elif name == 'clock':
        cr.arc(0, 0, s * .46, 0, math.tau)
        cr.stroke()
        cr.move_to(0, -s * .26)
        cr.line_to(0, 0)
        cr.line_to(s * .2, s * .12)
        cr.stroke()
    elif name == 'calendar':
        rrect(cr, -s * .46, -s * .4, s * .92, s * .84, s * .12)
        cr.stroke()
        cr.move_to(-s * .46, -s * .12)
        cr.line_to(s * .46, -s * .12)
        cr.stroke()
        for sx in (-.22, .22):
            cr.move_to(s * sx, -s * .52)
            cr.line_to(s * sx, -s * .28)
            cr.stroke()
    elif name == 'play':
        cr.arc(0, 0, s * .46, 0, math.tau)
        cr.stroke()
        cr.move_to(-s * .12, -s * .24)
        cr.line_to(s * .26, 0)
        cr.line_to(-s * .12, s * .24)
        cr.close_path()
        cr.fill()
    elif name == 'window':
        rrect(cr, -s * .48, -s * .4, s * .96, s * .8, s * .12)
        cr.stroke()
        cr.move_to(-s * .48, -s * .14)
        cr.line_to(s * .48, -s * .14)
        cr.stroke()
    elif name == 'bar':
        rrect(cr, -s * .5, -s * .34, s, s * .24, s * .12)
        cr.stroke()
        rrect(cr, -s * .5, s * .06, s * .56, s * .24, s * .12)
        cr.stroke()
    elif name == 'grid':
        for dx in (-1, 1):
            for dy in (-1, 1):
                rrect(cr, dx * s * .24 - s * .17, dy * s * .24 - s * .17, s * .34, s * .34, s * .07)
                cr.stroke()
    else:
        rrect(cr, -s * .48, -s * .38, s * .96, s * .64, s * .14)
        cr.stroke()
        cr.move_to(-s * .12, s * .26)
        cr.line_to(-s * .26, s * .46)
        cr.line_to(s * .08, s * .26)
        cr.stroke()
    cr.restore()


class App:
    def __init__(self, app):
        self.app = app
        self.ui = Ui(self.apply)
        self.t = 0.0
        self.open_sp = Spring(0, omega=17, zeta=.72)
        self.closing = False
        self.cats = []
        for group, items in ds_pages.CATEGORIES:
            self.cats.append((group, items))
        self.flat = [(k, t, icon, b) for _g, items in self.cats for (k, t, icon, b) in items]
        want = os.environ.get('DS_PAGE')
        self.cur = next((i for i, f in enumerate(self.flat) if f[0] == want), 0)
        self.prev_cur = None
        self.pages = {}
        self._start_scroll = float(os.environ.get('DS_SCROLL', '0') or 0)
        self.page_t = Spring(1, omega=18, zeta=.9)
        self.hl = Spring(self.cur, omega=22, zeta=.75)
        self.hover_side = None
        self.pointer = None
        self.toast_msg = None
        self.toast_sp = Spring(0, omega=22, zeta=.7)
        self.toast_until = 0.0
        self.toast_undo = None
        self.zones_side = []
        self.frame_tick = None
        self._fl = None
        self._busy = True
        self.thumb_queue = set()
        self.win = self.catcher = None
        self._build()

    # -------------------------------------------------------------- windows
    def _build(self):
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('ds-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.TOP)
        LS.set_namespace(catcher, 'desk-settings-catcher')
        for e in (LS.Edge.TOP, LS.Edge.RIGHT, LS.Edge.BOTTOM, LS.Edge.LEFT):
            LS.set_anchor(catcher, e, True)
        LS.set_exclusive_zone(catcher, -1)
        LS.set_keyboard_mode(catcher, LS.KeyboardMode.NONE)
        blank = Gtk.Box(hexpand=True, vexpand=True)
        click = Gtk.GestureClick()
        click.connect('pressed', lambda g, n, x, y: self.close())
        blank.add_controller(click)
        catcher.set_child(blank)
        self.catcher = catcher
        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('ds-win')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'desk-settings')
        LS.set_exclusive_zone(win, -1)
        LS.set_keyboard_mode(win, LS.KeyboardMode.ON_DEMAND)
        w, h = int(PW + 2 * PAD_WIN), int(PH + 2 * PAD_WIN)
        win.set_default_size(w, h)
        da = Gtk.DrawingArea()
        da.set_content_width(w)
        da.set_content_height(h)
        da.set_draw_func(self.draw)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_leave)
        da.add_controller(motion)
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect('pressed', self._on_press)
        da.add_controller(click)
        rc = Gtk.GestureClick()
        rc.set_button(3)
        rc.connect('pressed', lambda g, n, x, y: self.close())
        da.add_controller(rc)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self._on_scroll)
        da.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._on_key)
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        win.add_controller(keys)
        overlay = Gtk.Overlay()
        overlay.set_child(da)
        entry = Gtk.Entry()
        entry.add_css_class('ds-entry')
        entry.set_halign(Gtk.Align.START)
        entry.set_valign(Gtk.Align.START)
        entry.set_visible(False)
        entry.connect('activate', self._entry_commit)
        overlay.add_overlay(entry)
        self.entry, self.entry_row = entry, None
        self.ui.edit_cb = self.open_entry
        win.set_child(overlay)
        css = Gtk.CssProvider()
        css.load_from_string('window.ds-win { background: transparent; } window.ds-catcher { background: rgba(0,0,0,0.01); } entry.ds-entry { background: rgba(255,255,255,0.12); color: #fff; border: none; border-radius: 12px; padding: 0 12px; font-size: 14px; min-height: 0; box-shadow: none; outline: none; }')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win, self.da = win, da
        if self._start_scroll:
            pg0 = self.page(self.cur)
            pg0.target = self._start_scroll
            pg0.scroll.snap(self._start_scroll)
        THEME.refresh(force=True)
        self.catcher.present()
        self.win.present()
        self.start_frames()

    def close(self):
        if not self.closing:
            self.closing = True
            self.start_frames()

    def start_frames(self):
        if self.frame_tick is None:
            self._fl = None
            self.frame_tick = self.da.add_tick_callback(self._frame)

    def request_draw(self):
        GLib.idle_add(self.start_frames)

    # ---------------------------------------------------------------- data
    def page(self, i):
        key, title, icon, builder = self.flat[i]
        if key not in self.pages:
            self.pages[key] = builder(self)
        return self.pages[key]

    def apply(self, title, set_, value, old_get, set_back):
        old = old_get()

        def work():
            ok = set_(value)
            GLib.idle_add(self.toast, '%s 已更改' % title if ok else '%s 修改失败' % title,
                          (lambda: self._undo(set_, old, set_back)) if ok else None)
        threading.Thread(target=work, daemon=True).start()

    def _undo(self, set_, old, set_back):
        set_back(old)
        threading.Thread(target=lambda: set_(old), daemon=True).start()
        self.toast('已撤销')
        self.start_frames()

    def toast(self, msg, undo=None):
        self.toast_msg, self.toast_undo = msg, undo
        self.toast_until = time.monotonic() + (4.0 if undo else 2.2)
        self.toast_sp.t = 1.0
        self.start_frames()
        return False

    def load_thumb(self, path, store):
        def work():
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 420, 260, True)
                surf = gfx._surface_from_pixbuf(pb)
            except Exception:
                surf = None
            store[path] = surf
            GLib.idle_add(self.start_frames)
        threading.Thread(target=work, daemon=True).start()

    # --------------------------------------------------------------- frames
    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        gap = .0155
        if self._fl and now - self._fl < gap:
            return GLib.SOURCE_CONTINUE
        dt_ = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        THEME.refresh()
        self.ui.txt, self.ui.accent = THEME.text, THEME.accent
        self.t += dt_
        self.open_sp.t = 0.0 if self.closing else 1.0
        self.open_sp.z, self.open_sp.o = (.9, 26.0) if self.closing else (.72, 17.0)
        self.hl.t = float(self.cur)
        busy = False
        sps = [self.open_sp, self.page_t, self.hl, self.toast_sp]
        pg = self.page(self.cur)
        pg.target = max(0.0, min(pg.target, max(0.0, pg.height() - (VIEW_BOT - VIEW_TOP))))
        pg.scroll.t = pg.target
        sps.append(pg.scroll)
        for r in pg.rows():
            sps.extend(r.sp.values())
        if self.prev_cur is not None:
            sps.append(self.page(self.prev_cur).scroll)
        for sp in sps:
            sp.step(dt_)
            busy = busy or not sp.settled
        if time.monotonic() > self.toast_until and self.toast_sp.t == 1.0:
            self.toast_sp.t = 0.0
        if self.prev_cur is not None and self.page_t.settled and self.page_t.x >= .999:
            self.prev_cur = None
        self.da.queue_draw()
        if self.closing and self.open_sp.x < .01 and self.open_sp.settled:
            self.app.quit()
            return GLib.SOURCE_REMOVE
        if not busy and self.pointer is None and time.monotonic() > self.toast_until:
            self.frame_tick = None
            return GLib.SOURCE_REMOVE
        if not busy and not self._motion_recent():
            self.frame_tick = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    _last_motion = 0.0

    def _motion_recent(self):
        return time.monotonic() - self._last_motion < .25 or time.monotonic() < self.toast_until

    # ----------------------------------------------------------------- draw
    def draw(self, area, cr, W, H):
        try:
            self._draw(cr)
        except Exception:
            import traceback
            try:
                (HERE / 'error.txt').write_text(traceback.format_exc())
            except OSError:
                pass

    def _draw(self, cr):
        o = clamp(self.open_sp.x, 0, 1.15)
        a = clamp(self.open_sp.x * 1.6)
        if a < .01:
            return
        cr.translate(PAD_WIN + PW / 2, PAD_WIN + PH / 2)
        sc = .93 + .07 * min(1.1, o)
        cr.scale(sc, sc)
        cr.translate(-PW / 2, -PH / 2)
        cr.push_group()
        gfx.shadow(cr, 0, 0, PW, PH, 34, 1.6, 12)
        rrect(cr, 0, 0, PW, PH, 34)
        cr.set_source_rgb(*BLACK)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, .07)
        cr.set_line_width(1)
        cr.stroke()
        cr.save()
        rrect(cr, 0, 0, PW, PH, 34)
        cr.clip()
        ui = self.ui
        txt, acc = ui.txt, ui.accent
        ui.zones = []
        self.zones_side = []
        p = self.pointer
        ui.pointer = p
        # ---- sidebar
        cr.set_source_rgba(*txt, .035)
        cr.rectangle(0, 0, SIDE_W, PH)
        cr.fill()
        dl(cr, gfx.text_layout('桌面设置', 17, True), 26, 26, (*txt, 1))
        y = 78.0
        idx = 0
        item_y = []
        for group, items in self.cats:
            dl(cr, gfx.text_layout(group, 11.5, True), 28, y, (*txt, .4))
            y += 26
            for key, title, icon, _b in items:
                item_y.append(y)
                y += 42
                idx += 1
            y += 10
        # sliding highlight
        f = clamp(self.hl.x, 0, len(item_y) - 1)
        i0 = int(f)
        i1 = min(i0 + 1, len(item_y) - 1)
        hy = lerp(item_y[i0], item_y[i1], f - i0)
        rrect(cr, 12, hy - 2, SIDE_W - 24, 38, 13)
        cr.set_source_rgba(*acc, .26)
        cr.fill()
        idx = 0
        for group, items in self.cats:
            for key, title, icon, _b in items:
                iy = item_y[idx]
                hot = p is not None and 12 <= p[0] - PAD_WIN <= SIDE_W - 12 and iy - 2 <= p[1] - PAD_WIN <= iy + 36
                self.zones_side.append((idx, 12, iy - 2, SIDE_W - 24, 38))
                sel = 1 - clamp(abs(idx - self.hl.x))
                col = (*(acc if sel > .5 else txt), .55 + .45 * sel + (.12 if hot else 0))
                draw_icon(cr, icon, 38, iy + 17, 18, col)
                dl(cr, gfx.text_layout(title, 14, sel > .5), 60, iy + 8, col)
                idx += 1
        # ---- close button
        cbx, cby = PW - 44, 22.0
        chot = p is not None and abs(p[0] - PAD_WIN - cbx) < 16 and abs(p[1] - PAD_WIN - cby) < 16
        cr.arc(cbx, cby, 13, 0, math.tau)
        cr.set_source_rgba(*txt, .16 if chot else .07)
        cr.fill()
        cr.set_source_rgba(*txt, .85 if chot else .55)
        cr.set_line_width(1.6)
        cr.set_line_cap(1)
        for a_, b_ in ((-4.5, -4.5), (-4.5, 4.5)):
            cr.move_to(cbx + a_, cby + b_)
            cr.line_to(cbx - a_, cby - b_)
        cr.stroke()
        self.zones_side.append(('close', cbx - 16, cby - 16, 32, 32))
        # ---- content
        pt = clamp(self.page_t.x)
        self._draw_page(cr, self.cur, 1.0 if self.prev_cur is None else pt, (1 - pt) * 16 if self.prev_cur is not None else 0.0, True)
        if self.prev_cur is not None and pt < .98:
            self._draw_page(cr, self.prev_cur, 1 - pt, -pt * 12, False)
        # ---- toast
        ts = clamp(self.toast_sp.x)
        if ts > .01 and self.toast_msg:
            lay = gfx.text_layout(self.toast_msg, 13.5, True)
            lw, lh = gfx.text_size(lay)
            undo = self.toast_undo is not None
            ul = gfx.text_layout('撤销', 13.5, True)
            uw = gfx.text_size(ul)[0] + 24 if undo else 0
            w = lw + 40 + uw
            x0 = CX0 + (CW - w) / 2
            y0 = PH - 70 + (1 - ts) * 30
            cr.push_group()
            gfx.shadow(cr, x0, y0, w, 44, 22, 1.2, 6)
            rrect(cr, x0, y0, w, 44, 22)
            cr.set_source_rgb(.09, .1, .13)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, .1)
            cr.set_line_width(1)
            cr.stroke()
            dl(cr, lay, x0 + 20, y0 + 22 - lh / 2, (*txt, 1))
            if undo:
                hot = p is not None and x0 + w - uw - 6 <= p[0] - PAD_WIN <= x0 + w and y0 <= p[1] - PAD_WIN <= y0 + 44
                self.zones_side.append(('undo', x0 + w - uw - 6, y0, uw + 6, 44))
                dl(cr, ul, x0 + w - uw + 8, y0 + 22 - lh / 2, (*acc, 1))
            cr.pop_group_to_source()
            cr.paint_with_alpha(ts)
        cr.restore()
        cr.pop_group_to_source()
        cr.paint_with_alpha(a)

    def _draw_page(self, cr, i, alpha, dy, live):
        pg = self.page(i)
        ui = self.ui
        txt = ui.txt
        cr.push_group()
        dl(cr, gfx.text_layout(pg.title, 26, True), CX0, 30 + dy, (*txt, 1))
        cr.save()
        cr.rectangle(CX0 - 14, VIEW_TOP, CW + 28, VIEW_BOT - VIEW_TOP)
        cr.clip()
        off = pg.scroll.x
        # pointer in content coordinates
        saved = ui.pointer
        if saved is not None:
            ui.pointer = (saved[0] - PAD_WIN, saved[1] - PAD_WIN)
        keep = ui.zones
        if not live:
            ui.zones = []
        ui.view_top, ui.view_bottom = VIEW_TOP - 40, VIEW_BOT + 40
        end = ui.draw_page(cr, pg, CX0, VIEW_TOP - off + dy, CW, PH)
        if not live:
            ui.zones = keep
        ui.pointer = saved
        self.max_scroll = {i: max(0.0, pg.height() - (VIEW_BOT - VIEW_TOP))}
        cr.restore()
        # scrollbar
        total = pg.height()
        view = VIEW_BOT - VIEW_TOP
        if total > view + 2 and live:
            frac = view / total
            th = max(30.0, view * frac)
            ty = VIEW_TOP + (view - th) * (off / max(1.0, total - view))
            rrect(cr, PW - 12, ty, 4, th, 2)
            cr.set_source_rgba(*txt, .18)
            cr.fill()
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)

    # ----------------------------------------------------------------- input
    def _on_motion(self, ctl, x, y):
        self.pointer = (x, y)
        self._last_motion = time.monotonic()
        self.start_frames()

    def _on_leave(self, ctl):
        self.pointer = None
        self.start_frames()

    def _on_press(self, g, n, x, y):
        px, py = x - PAD_WIN, y - PAD_WIN
        # outside the panel (inside the shadow margin): ignore
        for z in reversed(self.zones_side):
            key, zx, zy, zw, zh = z
            if zx <= px <= zx + zw and zy <= py <= zy + zh:
                if key == 'close':
                    self.close()
                elif key == 'undo':
                    if self.toast_undo:
                        self.toast_undo()
                        self.toast_msg, self.toast_undo = '已撤销', None
                else:
                    self.select(key)
                self.start_frames()
                return
        for row, kind, zx, zy, zw, zh in reversed(self.ui.zones):
            if zx <= px <= zx + zw and zy <= py <= zy + zh and VIEW_TOP <= py <= VIEW_BOT:
                self.ui.last_zone = (zx, zy, zw, zh)
                row.click(self.ui, kind, px - zx, py - zy)
                break
        self.start_frames()

    def open_entry(self, row, rect):
        zx, zy, zw, zh = rect
        self.entry_row = row
        self.entry.set_text(row.value)
        self.entry.set_placeholder_text(row.ph)
        self.entry.set_margin_start(int(PAD_WIN + zx))
        self.entry.set_margin_top(int(PAD_WIN + zy))
        self.entry.set_size_request(int(zw), int(zh))
        self.entry.set_visible(True)
        self.entry.grab_focus()

    def close_entry(self):
        if self.entry.get_visible():
            self.entry.set_visible(False)
        self.entry_row = None

    def _entry_commit(self, entry):
        row = self.entry_row
        text = entry.get_text().strip()
        self.close_entry()
        if row is not None and text != row.value:
            old = row.value
            row.value = text
            self.apply(row.title, row.set_, text, lambda: old, lambda v, r=row: setattr(r, 'value', v))
        self.start_frames()

    def select(self, i):
        self.close_entry()
        if i == self.cur:
            return
        self.prev_cur = self.cur
        self.cur = i
        self.page_t.x, self.page_t.v, self.page_t.t = 0.0, 0.0, 1.0

    def _on_scroll(self, ctl, dx, dy):
        self.close_entry()
        pg = self.page(self.cur)
        limit = max(0.0, pg.height() - (VIEW_BOT - VIEW_TOP))
        pg.target = max(0.0, min(limit, pg.target + dy * 70))
        self.start_frames()
        return True

    def _on_key(self, ctl, keyval, keycode, state):
        name = Gdk.keyval_name(keyval)
        if self.entry.get_visible():
            if name == 'Escape':
                self.close_entry()
                return True
            return False            # typing goes to the entry
        if name == 'Escape':
            self.close()
        elif name in ('Down', 'Tab'):
            self.select(min(len(self.flat) - 1, self.cur + 1))
        elif name == 'Up':
            self.select(max(0, self.cur - 1))
        else:
            return False
        self.start_frames()
        return True


def main():
    app = Gtk.Application(application_id='dev.pr.DeskSettings2', flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def on_activate(a):
        if holder.get('app') is None:
            a.hold()
            holder['app'] = App(a)
        else:
            holder['app'].closing = False
            holder['app'].start_frames()

    app.connect('activate', on_activate)
    app.run([])


if __name__ == '__main__':
    main()

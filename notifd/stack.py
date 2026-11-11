"""Floating notification stack for the in-bar capsule style.

Clicking the bell opens no panel: the saved notifications drop out from under the bell as separate floating
cards, one after another (staggered springs). Each card can be swiped away or closed with its own x; the rest
slide up to fill the gap. Clicking anywhere else (or the bell again) folds the cards back up.
"""
import math
import time

import cairo
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

import gfx  # noqa: E402
from gfx import THEME, Spring, clamp, mix, rrect  # noqa: E402
from model import CRITICAL  # noqa: E402

CARD_W = 344
PADX = 18
WIN_W = CARD_W + 2 * PADX
GAP = 10
HEAD_H = 34
MAX_CARDS = 6
KICK = None
CM = 34         # shadow margin of a cached card bitmap
TOPPAD = 40     # window starts at the screen top so cards can leave the bell itself
STAGGER = .09
BELL_CX = 306   # bell centre, px from the screen's right edge


_kick_seq = [0]


def kick(strength=1.0):
    """Tell the bell widget that a card just left / returned, so the bell reacts."""
    import json
    import model
    _kick_seq[0] += 1
    try:
        model.write_json(model.STATE_DIR / 'bell-kick.json', dict(seq=_kick_seq[0], s=strength, t=time.time()))
    except OSError:
        pass


class Card:
    def __init__(self, item, delay):
        self.item = item
        self.n = item.n
        self.delay = delay
        self.born = time.monotonic()
        self.y = Spring(0, omega=24, zeta=.78)
        self.y_set = False
        self.a = Spring(0, omega=27, zeta=.58)
        self.dx = Spring(0, omega=22, zeta=.85)
        self.gone = False
        self.top = 0.0
        self.start = None
        self.returned = False
        self.cache = None
        self.cache_key = None
        self.slide = 0.0
        self.plain = False      # scrolled in/out of the list: plain fade, not flying to/from the bell


class Stack:
    def __init__(self, app, mgr, item_factory, anchor_right, pop_top, on_closed):
        self.app = app
        self.mgr = mgr
        self.make_item = item_factory
        self.anchor_right = anchor_right
        self.bell_r = BELL_CX          # bell centre, px from the screen's right edge
        self.pop_top = pop_top
        self.head_a = None
        self.on_closed = on_closed
        self.win = self.catcher = None
        self.cards = []
        self.is_open = False
        self.head_a = Spring(0, omega=15, zeta=.72)
        self.frame_tick = None
        self._fl = None
        self.pointer = None
        self.press = None
        self.drag_card = None
        self.region_key = None
        self.height = 200
        self.offset = 0          # how many (newer) notifications are scrolled off the top
        self.total = 0
        self._scroll_t = 0.0

    # ----------------------------------------------------------------- state
    def _entries(self):
        hist = list(reversed(self.mgr.history))
        self.total = len(hist)
        self.offset = max(0, min(self.offset, max(0, len(hist) - MAX_CARDS)))
        return hist[self.offset:self.offset + MAX_CARDS], max(0, len(hist) - MAX_CARDS - self.offset)

    def open(self):
        if self.is_open:
            return
        self._ensure_window()
        self.is_open = True
        self.offset = 0
        self.cards = []
        self._sync(initial=True)
        self.mgr.center_opened()
        self.catcher.present()
        self._start_frames()

    def _present_win(self):
        if self.is_open and self.win is not None:
            self.win.present()
        return False

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        for i, c in enumerate(self.cards):
            c.delay = i * .02
            c.born = time.monotonic()
        self._start_frames()

    def toggle(self):
        if self.is_open:
            self.close()
        else:
            self.open()

    def refresh(self):
        """History changed (new notification, dismissal elsewhere)."""
        if self.is_open:
            self._sync()

    def _sync(self, initial=False, scroll=0):
        entries, self.more = self._entries()
        have = {c.n.id: c for c in self.cards}
        new_cards = []
        for i, n in enumerate(entries):
            c = have.get(n.id)
            if c is not None and c.gone:
                c = None
            if c is None:
                c = Card(self.make_item(n), i * STAGGER if initial else 0)
                c.dx.snap(0)
                if scroll:
                    c.plain = True
                    c.a.snap(0)
                    c.a.t = 1.0
                    c.slide = 70.0 * scroll
            else:
                c.n = n
            new_cards.append(c)
        keep = {c.n.id for c in new_cards}
        for c in self.cards:
            if c.gone:
                new_cards.append(c)
            elif c.n.id not in keep:
                c.gone = True
                c.a.t = 0.0
                if scroll:
                    c.plain = True
                    c.dx.t = 0.0
                    c.y.t = c.y.x - 70.0 * scroll
                else:
                    c.dx.t = 460.0
                new_cards.append(c)
        self.cards = new_cards
        self._start_frames()

    # ---------------------------------------------------------------- windows
    def _ensure_window(self):
        if self.win is not None:
            return
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('notifd-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.TOP)
        LS.set_namespace(catcher, 'notifd-stack-catcher')
        for edge in (LS.Edge.TOP, LS.Edge.RIGHT, LS.Edge.BOTTOM, LS.Edge.LEFT):
            LS.set_anchor(catcher, edge, True)
        LS.set_exclusive_zone(catcher, -1)
        LS.set_keyboard_mode(catcher, LS.KeyboardMode.NONE)
        blank = Gtk.Box()
        blank.set_hexpand(True)
        blank.set_vexpand(True)
        outside = Gtk.GestureClick()
        outside.connect('pressed', lambda g, n, x, y: self.close())
        blank.add_controller(outside)
        catcher.set_child(blank)
        self.catcher = catcher
        # the cards' window must be mapped after the catcher so it stacks above it
        catcher.connect('map', lambda *_: GLib.timeout_add(40, self._present_win))

        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('notifd')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'notifd-stack')
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.RIGHT, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_margin(win, LS.Edge.TOP, 0)
        LS.set_margin(win, LS.Edge.RIGHT, self.anchor_right - PADX)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        win.set_default_size(WIN_W, self.height)
        da = Gtk.DrawingArea()
        da.set_content_width(WIN_W)
        da.set_content_height(self.height)
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
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self._on_scroll)
        da.add_controller(scroll)
        win.set_child(da)
        self.win, self.da = win, da

    def set_bell(self, bell_r):
        """The bell moved (measured on screen): cards fly out of it, and the stack sits so the bell is over it."""
        self.bell_r = float(bell_r)
        self.anchor_right = max(26.0, self.bell_r - 300.0)
        if self.win is not None:
            LS.set_margin(self.win, LS.Edge.RIGHT, int(self.anchor_right - PADX))

    def shutdown(self):
        if self.frame_tick is not None:
            self.da.remove_tick_callback(self.frame_tick)
            self.frame_tick = None
        for w in (self.win, self.catcher):
            if w is not None:
                w.destroy()
        self.win = self.catcher = None
        self.is_open = False
        self.cards = []

    # ----------------------------------------------------------------- frames
    def _start_frames(self):
        if self.win is not None and self.frame_tick is None:
            self._fl = None
            self.frame_tick = self.da.add_tick_callback(self._frame)

    def _layout(self):
        y = HEAD_H + 4
        for c in self.cards:
            if c.gone:
                continue
            c.top = y
            y += c.item.h + GAP
        if self.more or self.offset:
            y += 32
        return y

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        if self._fl and now - self._fl < .0155:
            return GLib.SOURCE_CONTINUE      # the panel runs at 165 Hz: animate at ~60 fps, a third of the work
        dt = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        THEME.refresh()
        total = self._layout()
        t = time.monotonic()
        self.head_a.t = 1.0 if self.is_open else 0.0
        self.head_a.z, self.head_a.o = (.72, 15.0) if self.is_open else (.95, 20.0)
        self.head_a.step(dt)
        busy = not self.head_a.settled
        for c in self.cards:
            if c.gone:
                pass
            else:
                ready = t - c.born >= c.delay
                if ready and self.is_open and c.start is None:
                    c.start = t
                    kick(1.0)
                if ready and not self.is_open and not c.returned:
                    c.returned = True
                    kick(.6)
                c.a.t = (1.0 if ready else 0.0) if self.is_open else (0.0 if ready else 1.0)
                c.a.z, c.a.o = (.72, 15.0) if self.is_open else (.95, 20.0)
                if not c.y_set:
                    c.y.snap(c.top + c.slide)
                    c.y_set = True
                c.y.t = c.top
            for sp in (c.a, c.y, c.dx):
                sp.step(dt)
                busy = busy or not sp.settled
            if not c.gone and t - c.born < c.delay:
                busy = True
        self.cards = [c for c in self.cards if not (c.gone and c.a.x < .02 and c.a.settled)]
        need = (int(total) + 40 + 19) // 20 * 20
        if need != self.height and self.is_open:
            self.height = need
            self.da.set_content_height(need + TOPPAD)
        self.da.queue_draw()
        self._update_region()
        if not self.is_open and not busy:
            self.win.set_visible(False)
            self.catcher.set_visible(False)
            self.frame_tick = None
            self.region_key = None
            self.cards = []
            return GLib.SOURCE_REMOVE
        if self.is_open and not busy:
            self.frame_tick = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        rects = []
        if self.head_a.x > .3:
            rects.append((PADX - 4, TOPPAD, CARD_W + 8, HEAD_H + 4))
        for c in self.cards:
            if not c.gone and c.a.x > .3:
                rects.append((PADX - 4, int(c.y.x) - 2 + TOPPAD, CARD_W + 8, int(c.item.h) + 6))
        key = tuple(rects)
        if key == self.region_key:
            return
        self.region_key = key
        region = cairo.Region()
        for r in rects:
            region.union(cairo.RectangleInt(*r))
        surface.set_input_region(region)

    # ------------------------------------------------------------------- draw
    def _chips(self):
        """Header chips: (key, label, x, w) laid out from the right edge."""
        out = []
        x = PADX + CARD_W
        for key, label in (('clear', '全部清除'), ('dnd', '免打扰 开' if self.mgr.dnd else '免打扰')):
            lay = gfx.text_layout(label, 12, True)
            w = gfx.text_size(lay)[0] + 26
            x -= w
            out.append((key, lay, x, w))
            x -= 8
        return out

    def draw(self, area, cr, W, H):
        th = THEME
        ha = clamp(self.head_a.x)
        cr.translate(0, TOPPAD)
        if ha > .01:
            cr.save()
            self._emerge(cr, PADX + CARD_W / 2, 18, self.head_a.x, self.head_a.v)
            ha = clamp(self.head_a.x * 3)
            cr.push_group()
            for key, lay, x, w in self._chips():
                hot = self._hit_chip() == key
                on = key == 'dnd' and self.mgr.dnd
                rrect(cr, x, 4, w, 28, 14)
                cr.set_source_rgba(*((.16, .16, .17) if hot else (0, 0, 0)), 1)
                cr.fill_preserve()
                cr.set_source_rgba(*(th.accent if on else th.text), .35 if on else .12)
                cr.set_line_width(1)
                cr.stroke()
                gfx.draw_layout(cr, lay, x + 13, 4 + (28 - gfx.text_size(lay)[1]) / 2, (*(th.accent if on else th.text), .95))
            title = gfx.text_layout('通知 · %d' % len(self.mgr.history) if self.mgr.history else '没有通知', 13, True)
            cr.pop_group_to_source()
            cr.paint_with_alpha(ha)
            # title on a small pill so it reads on any wallpaper
            tw = gfx.text_size(title)[0] + 26
            cr.push_group()
            rrect(cr, PADX, 4, tw, 28, 14)
            cr.set_source_rgba(0, 0, 0, 1)
            cr.fill()
            gfx.draw_layout(cr, title, PADX + 13, 4 + (28 - gfx.text_size(title)[1]) / 2, (*th.text, .95))
            cr.pop_group_to_source()
            cr.paint_with_alpha(ha)
            cr.restore()
        for c in self.cards:
            self._draw_card(cr, c)
        if (self.more or self.offset) and self.is_open:
            hint = ('↓ 滚轮查看更早的 %d 条' % self.more) if self.more else '已到最早'
            if self.offset:
                hint = '↑ 较新 %d 条 · ' % self.offset + hint
            lay = gfx.text_layout(hint, 11.5)
            gfx.draw_layout(cr, lay, PADX + CARD_W / 2 - gfx.text_size(lay)[0] / 2, self._layout() - 22,
                            (*th.text, .6 * ha))

    def _emerge(self, cr, cx, cy, p, v):
        """Move/scale/tilt the next drawing so it travels out of (or back into) the bell."""
        ox = WIN_W - (self.bell_r - (self.anchor_right - PADX))
        oy = -20.0
        q = max(0.0, p)
        px = q ** 1.5 if q < 1 else q
        curx = ox + (cx - ox) * px
        cury = oy + (cy - oy) * q
        tilt = max(-.32, min(.32, -v * .03))
        s = .06 + .94 * min(1.08, q)
        cr.translate(curx, cury)
        cr.rotate(tilt)
        cr.scale(s, s)
        cr.translate(-cx, -cy)

    def _render_card(self, c, hov, xhot):
        """Draw a card (shadow included) into its own 2x surface; animation then only paints this bitmap."""
        th = THEME
        it, n = c.item, c.n
        crit = n.urgency == CRITICAL
        w, h = CARD_W, it.h
        M = CM
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int((w + 2 * M) * 2), int(math.ceil(h + 2 * M) * 2))
        surf.set_device_scale(2, 2)
        cr = cairo.Context(surf)
        x0 = y0 = M
        gfx.shadow(cr, x0, y0, w, h, 22, 1.2)
        rrect(cr, x0, y0, w, h, 22)
        if gfx.style() == 'glass':
            gfx.glass_flat(cr)
        else:
            cr.set_source_rgba(0, 0, 0, 1)
            cr.fill_preserve()
        cr.set_source_rgba(*(th.danger if crit else th.text), .40 if crit else .12)
        cr.set_line_width(1)
        cr.stroke()
        gfx.draw_layout(cr, it.l_app, x0 + 18, y0 + 14, (*th.text, .55))
        if hov:
            bx, by = x0 + w - 32, y0 + 8
            cr.arc(bx + 12, by + 12, 12, 0, 6.2832)
            cr.set_source_rgba(*th.text, .22 if xhot else .1)
            cr.fill()
            cr.set_source_rgba(*th.text, .85)
            cr.set_line_width(1.6)
            cr.move_to(bx + 8, by + 8)
            cr.line_to(bx + 16, by + 16)
            cr.move_to(bx + 16, by + 8)
            cr.line_to(bx + 8, by + 16)
            cr.stroke()
        else:
            t = gfx.text_layout(gfx.ago(n.ts), 11)
            gfx.draw_layout(cr, t, x0 + w - 18 - gfx.text_size(t)[0], y0 + 14, (*th.text, .45))
        gfx.draw_layout(cr, it.l_sum, x0 + 18, y0 + it.sum_y, (*th.text, 1))
        if it.l_body is not None:
            gfx.draw_layout(cr, it.l_body, x0 + 18, y0 + it.body_y, (*th.text, .72))
        return surf

    def _draw_card(self, cr, c):
        if clamp(c.a.x) < .01:
            return
        th = THEME
        it, n = c.item, c.n
        w, h = CARD_W, it.h
        x0 = PADX + c.dx.x
        y0 = c.y.x
        swipe_fade = 1 - clamp(abs(c.dx.x) / 330)
        hov = self._card_at(self.pointer) is c
        xhot = hov and self._on_close(c, self.pointer)
        key = (hov, xhot, gfx.ago(n.ts), th.bg, th.text, n.id, n.summary)
        if c.cache is None or c.cache_key != key:
            c.cache, c.cache_key = self._render_card(c, hov, xhot), key
        cr.save()
        if not c.plain:
            self._emerge(cr, x0 + w / 2, y0 + h / 2, c.a.x, c.a.v)
        cr.set_source_surface(c.cache, x0 - CM, y0 - CM)
        cr.paint_with_alpha((clamp(c.a.x) if c.plain else clamp(c.a.x * 3)) * swipe_fade)
        cr.restore()

    # ------------------------------------------------------------------ input
    def _card_at(self, p):
        if p is None:
            return None
        px, py = p
        for c in self.cards:
            if c.gone:
                continue
            if PADX <= px <= PADX + CARD_W and c.y.x <= py <= c.y.x + c.item.h:
                return c
        return None

    def _on_close(self, c, p):
        if p is None:
            return False
        bx, by = PADX + c.dx.x + CARD_W - 32, c.y.x + 8
        return bx - 4 <= p[0] <= bx + 28 and by - 4 <= p[1] <= by + 28

    def _hit_chip(self):
        p = self.pointer
        if p is None:
            return None
        for key, lay, x, w in self._chips():
            if x <= p[0] <= x + w and 4 <= p[1] <= 32:
                return key
        return None

    def _on_scroll(self, ctl, dx, dy):
        """Mouse wheel pages through the older notifications, one card per notch."""
        if not self.is_open or abs(dy) < .01:
            return False
        now = time.monotonic()
        if now - self._scroll_t < .09:
            return True
        self._scroll_t = now
        step = 1 if dy > 0 else -1
        limit = max(0, self.total - MAX_CARDS)
        new = max(0, min(limit, self.offset + step))
        if new != self.offset:
            self.offset = new
            self._sync(scroll=step)
        return True

    def _on_motion(self, ctl, x, y):
        self.pointer = (x, y - TOPPAD)
        self._start_frames()

    def _on_leave(self, ctl):
        self.pointer = None
        self._start_frames()

    def _drag_begin(self, g, x, y):
        y -= TOPPAD
        self.press = (x, y)
        self.pointer = (x, y)
        self.drag_card = self._card_at((x, y))
        self._start_frames()

    def _drag_update(self, g, dx, dy):
        c = self.drag_card
        if c is not None and abs(dx) > 6:
            c.dx.x = c.dx.t = dx
            c.dx.v = 0.0
            self._start_frames()

    def _drag_end(self, g, dx, dy):
        c, self.drag_card = self.drag_card, None
        press, self.press = self.press, None
        if press is None:
            return
        if abs(dx) <= 6 and abs(dy) <= 6:
            chip = self._hit_chip()
            if chip == 'clear':
                self.mgr.clear_all()
                self.close()
            elif chip == 'dnd':
                self.mgr.toggle_dnd()
                self._start_frames()
            elif c is not None:
                if self._on_close(c, press):
                    self._dismiss(c)
                elif c.item.default_action:
                    self.mgr.invoke_action(c.n.id, 'default')
                    self._dismiss(c)
            return
        if c is not None:
            if abs(dx) > 90:
                self._dismiss(c, 1 if dx > 0 else -1)
            else:
                c.dx.t = 0.0
                self._start_frames()

    def _dismiss(self, c, direction=1):
        c.gone = True
        c.dx.t = 460.0 * direction
        c.a.t = 0.0
        self.mgr.dismiss_from_center(c.n.id)
        self._sync()

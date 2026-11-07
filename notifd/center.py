"""Notification centre: a full-height panel with grouped, animated history cards."""
import math
import time

import cairo
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gdk, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

import gfx  # noqa: E402
from gfx import THEME, Spring, clamp, mix, rrect  # noqa: E402
from model import CRITICAL  # noqa: E402

PANEL_W = 424
PAD = 16
CARD_W = PANEL_W - 2 * PAD
TOP_MARGIN = 42
BOTTOM_MARGIN = 12
RIGHT_PAD = 10
HEADER_H = 82
GAP = 8
RADIUS = 30


class Card:
    def __init__(self, n):
        self.n = n
        self.sig = None
        self.build()
        self.y = Spring(0, omega=30, zeta=.9)
        self.enter = Spring(0, omega=22, zeta=.68)
        self.x = Spring(0, omega=26, zeta=.85)
        self.hover = Spring(0, omega=30, zeta=1.0)
        self.collapse = Spring(1, omega=26, zeta=1.0)
        self.placed = False
        self.leaving = False
        self.delay = 0.0
        self.entered = False
        self.dragging = False
        self.born = time.monotonic()
        self.finished = False

    def build(self):
        n = self.n
        sig = (n.summary, n.body, n.app)
        if sig == self.sig:
            return
        self.sig = sig
        tw = CARD_W - 12 - 36 - 12 - 12
        self.l_app = gfx.make_layout(n.app or '通知', 11, True, width=tw - 80, lines=1)
        self.l_sum = gfx.make_layout(n.summary or '（无标题）', 13.5, True, width=tw, lines=2)
        y = 12 + 16
        self.sum_y = y
        y += gfx.text_size(self.l_sum)[1]
        self.l_body = None
        if n.body.strip():
            self.l_body = gfx.make_layout(gfx.safe_markup(n.body), 12, width=tw, lines=3, markup=True)
            y += 2
            self.body_y = y
            y += gfx.text_size(self.l_body)[1]
        self.h = max(60, y + 12)
        self.icon_surf = gfx.app_icon_surface(n, 24)


def day_bucket(ts):
    now = time.localtime()
    t = time.localtime(ts)
    today = (now.tm_year, now.tm_yday)
    if (t.tm_year, t.tm_yday) == today:
        return 0, '今天'
    y = time.localtime(time.time() - 86400)
    if (t.tm_year, t.tm_yday) == (y.tm_year, y.tm_yday):
        return 1, '昨天'
    return 2, '更早'


class Center:
    def __init__(self, app, mgr):
        self.app = app
        self.mgr = mgr
        self.win = None
        self.opening = False
        self.cards = {}
        self.sec_y = {}
        self.open_s = Spring(0, omega=24, zeta=.62)
        self.scroll = Spring(0, omega=32, zeta=1.0)
        self.dnd_knob = Spring(1.0 if mgr.dnd else 0.0, omega=34, zeta=.6)
        self.clear_press = Spring(0, omega=40, zeta=.6)
        self.tick_id = None
        self.last = None
        self.hits = []
        self.pointer = None
        self.press = None
        self.content_h = 0
        self.view_h = 0
        self.t0 = time.monotonic()
        self.clearing = False
        self.sync()

    @property
    def is_open(self):
        return self.opening

    # ---------------------------------------------------------------- window
    def _ensure_window(self):
        if self.win is not None:
            return
        # 1) a full-screen window that draws nothing: dims the screen and closes the centre on click
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('notifd-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.OVERLAY)
        LS.set_namespace(catcher, 'notifd-catcher')
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
        # 2) the panel itself: only as wide as the panel, so redraws stay cheap
        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('notifd-center')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'notifd-center')
        for edge in (LS.Edge.TOP, LS.Edge.RIGHT, LS.Edge.BOTTOM):
            LS.set_anchor(win, edge, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_margin(win, LS.Edge.TOP, TOP_MARGIN)
        LS.set_margin(win, LS.Edge.BOTTOM, BOTTOM_MARGIN)
        LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
        win.set_default_size(PANEL_W + RIGHT_PAD + 36, 400)
        da = Gtk.DrawingArea()
        da.set_hexpand(True)
        da.set_vexpand(True)
        da.set_draw_func(self.draw)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self.on_motion)
        motion.connect('leave', lambda c: setattr(self, 'pointer', None))
        da.add_controller(motion)
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect('drag-begin', self.on_drag_begin)
        drag.connect('drag-update', self.on_drag_update)
        drag.connect('drag-end', self.on_drag_end)
        da.add_controller(drag)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self.on_scroll)
        da.add_controller(scroll)
        key = Gtk.EventControllerKey()
        key.connect('key-pressed', self.on_key)
        win.add_controller(key)
        win.set_child(da)
        self.win, self.da = win, da

    # ------------------------------------------------------------- lifecycle
    def toggle(self):
        if self.opening:
            self.close()
        else:
            self.open()

    def open(self):
        self._ensure_window()
        self.opening = True
        self.sync()
        self.scroll.snap(0)
        self.scroll.t = 0
        self.t0 = time.monotonic()
        for i, c in enumerate(self.ordered()):
            c.enter.snap(0)
            c.enter.t = 0
            c.entered = False
            c.delay = .10 + i * .035
        self.open_s.x = 0
        self.open_s.t = 1
        self.catcher.present()
        self.win.present()
        GLib.idle_add(lambda: self.catcher.add_css_class('dim') or False)
        self.mgr.center_opened()
        self._ensure_tick()

    def close(self):
        if not self.opening:
            return
        self.opening = False
        self.open_s.omega, self.open_s.zeta = 24, 1.0
        self.open_s.t = 0
        self.catcher.remove_css_class('dim')
        self._ensure_tick()

    def refresh(self, new_id=None, cleared=False):
        self.sync(new_id)
        self.dnd_knob.t = 1.0 if self.mgr.dnd else 0.0
        if self.win is not None:
            self._ensure_tick()

    def sync(self, new_id=None):
        """Mirror the manager's history into persistent card states."""
        live = {}
        for n in self.mgr.history:
            c = self.cards.get(n.id)
            if c is None:
                c = Card(n)
                if new_id == n.id and self.opening:
                    c.delay = 0.0
                elif self.opening:
                    c.entered = True
                    c.enter.snap(1)
                    c.enter.t = 1
                    c.placed = False
            else:
                c.n = n
                c.build()
            live[n.id] = c
        self.cards = live

    def ordered(self):
        return sorted(self.cards.values(), key=lambda c: -c.n.ts)

    # ------------------------------------------------------------- animation
    def _ensure_tick(self):
        if self.tick_id is None and self.win is not None:
            self.last = None
            self.tick_id = self.da.add_tick_callback(self._tick)

    def _tick(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = (now - self.last) if self.last else 1 / 60
        self.last = now
        THEME.refresh()
        self._step(dt)
        self._frame = getattr(self, '_frame', 0) + 1
        # the empty-state illustration only needs ~20 fps; everything else redraws every frame
        if self.cards or not self.opening or self._frame % 3 == 0 or not self.open_s.settled:
            self.da.queue_draw()
        if not self.opening and self.open_s.settled and self.open_s.x < .01:
            self.win.set_visible(False)
            self.catcher.set_visible(False)
            self.tick_id = None
            return GLib.SOURCE_REMOVE
        if self.opening:
            why = self._busy()
            if why is None:
                self.tick_id = None
                return GLib.SOURCE_REMOVE
            import os
            if os.environ.get('NOTIFD_DEBUG') and int(now * 2) != getattr(self, '_dbg_t', None):
                self._dbg_t = int(now * 2)
                from notifd import log
                log('busy: ' + why)
        return GLib.SOURCE_CONTINUE

    def _busy(self):
        """Reason string while anything is moving (None when everything has settled)."""
        if self.clearing or self.press:
            return 'clearing/press'
        named = [('open', self.open_s), ('scroll', self.scroll), ('dnd', self.dnd_knob), ('clearp', self.clear_press)]
        for c in self.cards.values():
            if not c.entered or c.leaving:
                return f'card entered={c.entered} leaving={c.leaving}'
            named += [('y', c.y), ('enter', c.enter), ('x', c.x), ('hover', c.hover), ('collapse', c.collapse)]
        named += [('sec', sp) for sp in self.sec_y.values()]
        for name, sp in named:
            if not sp.settled:
                return f'spring {name} x={sp.x:.4f} t={sp.t:.4f} v={sp.v:.4f}'
        return 'empty-state' if not self.cards else None

    def _step(self, dt):
        for sp in (self.open_s, self.scroll, self.dnd_knob, self.clear_press):
            sp.step(dt)
        age = time.monotonic() - self.t0
        cards = self.ordered()
        hot = self._hover_card()
        for c in cards:
            if self.opening and not c.entered and age >= c.delay:
                c.entered = True
                c.enter.t = 1
            c.hover.t = 1.0 if (c is hot or c.dragging) else 0.0
            if c.leaving and age >= c.delay:
                c.x.t = PANEL_W
                if c.x.x > PANEL_W * .45:
                    c.collapse.t = 0
            for sp in (c.y, c.enter, c.x, c.hover, c.collapse):
                sp.step(dt)
            if c.leaving and c.collapse.x < .02 and not c.finished:
                c.finished = True
                if self.clearing:
                    continue
                self.mgr.dismiss_from_center(c.n.id)
        if self.clearing and cards and all(c.finished for c in cards):
            self.clearing = False
            self.mgr.clear_all()
        for sp in list(self.sec_y.values()):
            sp.step(dt)

    # ----------------------------------------------------------------- layout
    def layout_entries(self):
        """Returns [('sec', label, y_target), ('card', Card, y_target)] and total height."""
        out = []
        y = 0.0
        last_bucket = None
        counts = {}
        for c in self.ordered():
            counts[day_bucket(c.n.ts)[1]] = counts.get(day_bucket(c.n.ts)[1], 0) + 1
        for c in self.ordered():
            b, label = day_bucket(c.n.ts)
            if b != last_bucket:
                last_bucket = b
                out.append(('sec', label, y, counts[label]))
                y += 30
            out.append(('card', c, y))
            y += c.h * c.collapse.x + GAP * clamp(c.collapse.x * 1.5)
        return out, y

    # ------------------------------------------------------------------- draw
    def draw(self, area, cr, W, H):
        th = THEME
        self.hits = []
        slide = (1 - self.open_s.x) * (PANEL_W + 60)
        px = W - RIGHT_PAD - PANEL_W + slide
        py = 0
        ph = H
        self.panel_rect = (px, py, PANEL_W, ph)
        if self.open_s.x < .005 and not self.opening:
            return
        gfx.shadow(cr, px, py, PANEL_W, ph, RADIUS, 2.2, dy=10)
        rrect(cr, px, py, PANEL_W, ph, RADIUS)
        cr.set_source_rgba(*mix(th.bg, th.text, .045), .985)
        cr.fill_preserve()
        cr.set_source_rgba(*th.text, .10)
        cr.set_line_width(1)
        cr.stroke()
        cr.save()
        rrect(cr, px, py, PANEL_W, ph, RADIUS)
        cr.clip()
        self._draw_header(cr, px, py)
        # scrolling list
        top = py + HEADER_H
        view_h = ph - HEADER_H - 10
        self.view_h = view_h
        cr.save()
        cr.rectangle(px, top, PANEL_W, view_h)
        cr.clip()
        entries, total = self.layout_entries()
        self.content_h = total
        max_scroll = max(0.0, total - view_h)
        self.scroll.t = clamp(self.scroll.t, 0, max_scroll) if max_scroll >= 0 else 0
        sy = top - self.scroll.x
        for kind, obj, ty, *rest in entries:
            if kind == 'sec':
                sp = self.sec_y.setdefault(obj, Spring(ty, omega=30, zeta=.9))
                sp.t = ty
                self._draw_section(cr, px + PAD, sy + sp.x, obj, rest[0])
            else:
                c = obj
                c.y.t = ty
                if not c.placed:
                    c.y.snap(ty)
                    c.placed = True
                self._draw_card(cr, c, px + PAD, sy + c.y.x, top, top + view_h)
        if not entries:
            self._draw_empty(cr, px, top, view_h)
        cr.restore()
        # scrollbar
        if total > view_h:
            frac = view_h / total
            bh = max(36, view_h * frac)
            by = top + (self.scroll.x / max_scroll) * (view_h - bh) if max_scroll else top
            cr.set_source_rgba(*th.text, .22)
            rrect(cr, px + PANEL_W - 8, by, 3.5, bh, 1.75)
            cr.fill()
        cr.restore()

    # ---- header -----------------------------------------------------------
    def _draw_header(self, cr, px, py):
        th = THEME
        n = len(self.cards)
        lay = gfx.text_layout('通知', 22, True)
        gfx.draw_layout(cr, lay, px + PAD + 4, py + 16, (*th.text, 1))
        sub = f'{n} 条通知' if n else '一切都处理好了'
        gfx.draw_layout(cr, gfx.text_layout(sub, 12), px + PAD + 4, py + 48, (*th.text, .55))
        # clear-all pill
        cw, chh = 64, 34
        cx = px + PANEL_W - PAD - cw
        cy = py + 22
        press = clamp(self.clear_press.x)
        hov = self._hit_kind('clear')
        rrect(cr, cx - press * 2, cy - press * 1, cw + press * 4, chh + press * 2, 17)
        cr.set_source_rgba(*th.text, .10 + .06 * hov + .08 * press)
        cr.fill()
        lay = gfx.text_layout('清除', 12.5, True)
        lw, lh = gfx.text_size(lay)
        gfx.draw_layout(cr, lay, cx + (cw - lw) / 2, cy + (chh - lh) / 2, (*th.text, .9))
        self.hits.append(('clear', (cx, cy, cw, chh), None))
        # DND toggle
        tw_, th_ = 70, 34
        tx = cx - 10 - tw_
        on = clamp(self.dnd_knob.x)
        rrect(cr, tx, cy, tw_, th_, 17)
        cr.set_source_rgba(*mix(mix(th.bg, th.text, .14), th.accent, on), 1)
        cr.fill()
        kx = tx + 17 + (tw_ - 34) * on
        cr.arc(kx, cy + 17, 13 + .8 * math.sin(on * math.pi), 0, gfx.TAU)
        cr.set_source_rgba(1, 1, 1, .95)
        cr.fill()
        # icon inside knob: bell -> moon
        cr.save()
        cr.translate(kx, cy + 17)
        cr.set_source_rgba(*mix((.2, .2, .25), th.accent, on), 1)
        if on > .5:
            cr.arc(0, 0, 6, 0, gfx.TAU)
            cr.fill()
            cr.arc(2.8, -1.8, 5.2, 0, gfx.TAU)
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_OVER)
        else:
            cr.set_line_width(1.6)
            cr.move_to(-5, 3); cr.curve_to(-5, 3, -3.5, 0, -3.5, -2); cr.curve_to(-3.5, -6, 3.5, -6, 3.5, -2)
            cr.curve_to(3.5, 0, 5, 3, 5, 3); cr.close_path()
            cr.stroke()
            cr.arc(0, 5.6, 1.1, 0, gfx.TAU)
            cr.fill()
        cr.restore()
        if on < .5:
            gfx.draw_layout(cr, gfx.text_layout('勿扰', 11, True), tx + 36, cy + 10, (*th.text, .65))
        self.hits.append(('dnd', (tx, cy, tw_, th_), None))

    # ---- section label -----------------------------------------------------
    def _draw_section(self, cr, x, y, label, count):
        lay = gfx.text_layout(label, 12, True)
        gfx.draw_layout(cr, lay, x + 4, y + 6, (*THEME.text, .55))
        lw, _ = gfx.text_size(lay)
        lay2 = gfx.text_layout(str(count), 11, True)
        c2w, c2h = gfx.text_size(lay2)
        bx = x + 4 + lw + 8
        rrect(cr, bx, y + 5, c2w + 12, 18, 9)
        cr.set_source_rgba(*THEME.text, .10)
        cr.fill()
        gfx.draw_layout(cr, lay2, bx + 6, y + 5 + (18 - c2h) / 2, (*THEME.text, .6))

    # ---- card --------------------------------------------------------------
    def _draw_card(self, cr, c, x, y, view_top, view_bot):
        th = THEME
        n = c.n
        h = c.h * clamp(c.collapse.x)
        if y + h < view_top - 4 or y > view_bot + 4 or h < 2:
            return
        enter = clamp(c.enter.x, 0, 1.1)
        alpha = clamp(min(1.0, enter * 1.6)) * clamp(1 - c.x.x / (PANEL_W * .6)) * clamp(c.collapse.x * 1.4)
        if alpha <= .005:
            return
        ox = c.x.x + (1 - enter) * 46
        hv = clamp(c.hover.x)
        cx, cy = x + ox, y
        cr.save()
        cr.push_group()
        # card body (squashes as it collapses)
        rrect(cr, cx, cy, CARD_W, h, 20)
        cr.set_source_rgba(*mix(th.card, th.card_hi, hv), 1)
        cr.fill_preserve()
        crit = n.urgency == CRITICAL
        cr.set_source_rgba(*(th.danger if crit else th.text), .38 if crit else .08 + .06 * hv)
        cr.set_line_width(1)
        cr.stroke()
        if h >= c.h * .85:
            col = th.danger if crit else gfx.avatar_colour(n.app or n.summary)
            ax, ay = cx + 12 + 18, cy + 12 + 18
            # tiny pop when the card first lands
            pop = 1 + .10 * max(0, 1 - (time.monotonic() - c.born) * 2.2) * math.sin((time.monotonic() - c.born) * 22)
            cr.save()
            cr.translate(ax, ay)
            cr.scale(pop, pop)
            cr.arc(0, 0, 18, 0, gfx.TAU)
            cr.set_source_rgba(*col, .22)
            cr.fill()
            if c.icon_surf is not None:
                gfx.draw_surface_fit(cr, c.icon_surf, 0, 0, 22)
            else:
                lay = gfx.text_layout(gfx.initial(n.app or n.summary), 16, True)
                lw, lh = gfx.text_size(lay)
                gfx.draw_layout(cr, lay, -lw / 2, -lh / 2, (*col, 1))
            cr.restore()
            tx = cx + 12 + 36 + 12
            gfx.draw_layout(cr, c.l_app, tx, cy + 12, (*th.text, .55))
            ago = gfx.text_layout(gfx.ago(n.ts), 11)
            aw, _ = gfx.text_size(ago)
            gfx.draw_layout(cr, ago, cx + CARD_W - 12 - aw, cy + 12, (*th.text, .45 * (1 - hv)))
            gfx.draw_layout(cr, c.l_sum, tx, cy + c.sum_y, (*th.text, .97))
            if c.l_body is not None:
                gfx.draw_layout(cr, c.l_body, tx, cy + c.body_y, (*th.text, .70))
            if hv > .02:
                bx, by = cx + CARD_W - 22, cy + 22
                cr.arc(bx, by, 10, 0, gfx.TAU)
                cr.set_source_rgba(*th.text, .14 * hv)
                cr.fill()
                cr.set_source_rgba(*th.text, .85 * hv)
                cr.set_line_width(1.5)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.move_to(bx - 3.3, by - 3.3); cr.line_to(bx + 3.3, by + 3.3)
                cr.move_to(bx + 3.3, by - 3.3); cr.line_to(bx - 3.3, by + 3.3)
                cr.stroke()
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)
        cr.restore()
        if not c.leaving:
            self.hits.append(('card', (cx, cy, CARD_W, h), c))

    # ---- empty state ---------------------------------------------------------
    def _draw_empty(self, cr, px, top, view_h):
        th = THEME
        t = time.monotonic()
        cx, cy = px + PANEL_W / 2, top + view_h * .38
        bob = math.sin(t * 2.2) * 6
        # soft glow
        g = cairo.RadialGradient(cx, cy + bob, 6, cx, cy + bob, 70)
        g.add_color_stop_rgba(0, *th.accent, .28)
        g.add_color_stop_rgba(1, *th.accent, 0)
        cr.set_source(g)
        cr.arc(cx, cy + bob, 70, 0, gfx.TAU)
        cr.fill()
        # bell
        cr.save()
        cr.translate(cx, cy + bob)
        cr.rotate(math.sin(t * 1.6) * .10)
        cr.set_source_rgba(*th.accent, .95)
        cr.move_to(-24, 20)
        cr.curve_to(-24, 20, -16, 8, -16, -6)
        cr.curve_to(-16, -26, 16, -26, 16, -6)
        cr.curve_to(16, 8, 24, 20, 24, 20)
        cr.close_path()
        cr.fill()
        cr.arc(0, -28, 3.4, 0, gfx.TAU)
        cr.fill()
        cr.arc(0, 25 + math.sin(t * 3.2) * 1.5, 5.4, 0, gfx.TAU)
        cr.fill()
        cr.restore()
        # twinkling sparkles
        for i, (sx, sy, ph) in enumerate(((-52, -28, 0), (56, -10, 1.7), (-34, 34, 3.1), (46, 38, 4.4))):
            s = (math.sin(t * 2.6 + ph) + 1) / 2
            cr.save()
            cr.translate(cx + sx, cy + sy + bob * .4)
            cr.rotate(t * .6 + i)
            cr.set_source_rgba(*th.text, .15 + .6 * s)
            r = 2 + 4.5 * s
            cr.move_to(0, -r); cr.line_to(r * .28, -r * .28); cr.line_to(r, 0); cr.line_to(r * .28, r * .28)
            cr.line_to(0, r); cr.line_to(-r * .28, r * .28); cr.line_to(-r, 0); cr.line_to(-r * .28, -r * .28)
            cr.close_path()
            cr.fill()
            cr.restore()
        lay = gfx.text_layout('没有新通知', 15, True)
        lw, _ = gfx.text_size(lay)
        gfx.draw_layout(cr, lay, cx - lw / 2, cy + 82, (*th.text, .85))
        lay = gfx.text_layout('新的消息会出现在这里', 12)
        lw, _ = gfx.text_size(lay)
        gfx.draw_layout(cr, lay, cx - lw / 2, cy + 108, (*th.text, .45))

    # ----------------------------------------------------------------- input
    def _hit_kind(self, kind):
        if self.pointer is None:
            return 0.0
        px, py = self.pointer
        for k, (x, y, w, h), _ in self.hits:
            if k == kind and x <= px <= x + w and y <= py <= y + h:
                return 1.0
        return 0.0

    def _hover_card(self):
        if self.pointer is None:
            return None
        px, py = self.pointer
        top = self.panel_rect[1] + HEADER_H if hasattr(self, 'panel_rect') else 0
        if py < top:
            return None
        for k, (x, y, w, h), obj in self.hits:
            if k == 'card' and x <= px <= x + w and y <= py <= y + h:
                return obj
        return None

    def _at(self, x, y):
        for k, (rx, ry, rw, rh), obj in reversed(self.hits):
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                if k == 'card' and y < self.panel_rect[1] + HEADER_H:
                    continue
                return k, obj, (rx, ry, rw, rh)
        return None

    def on_motion(self, ctl, x, y):
        self.pointer = (x, y)
        self._ensure_tick()

    def on_drag_begin(self, g, x, y):
        hit = self._at(x, y)
        self.press = dict(x=x, y=y, hit=hit, moved=False)
        if hit and hit[0] == 'clear':
            self.clear_press.t = 1

    def on_drag_update(self, g, dx, dy):
        p = self.press
        if not p or not p['hit'] or p['hit'][0] != 'card':
            return
        c = p['hit'][1]
        if abs(dx) > 6 or p['moved']:
            p['moved'] = True
            c.dragging = True
            c.x.snap(max(-20.0, dx))
            c.x.t = c.x.x
            self._ensure_tick()

    def on_drag_end(self, g, dx, dy):
        p, self.press = self.press, None
        self.clear_press.t = 0
        if not p:
            return
        hit = p['hit']
        if hit is None:
            return
        kind, obj, rect = hit
        if kind == 'card':
            c = obj
            if p['moved']:
                c.dragging = False
                if dx > 110:
                    self.dismiss(c)
                else:
                    c.x.omega, c.x.zeta = 30, .55
                    c.x.t = 0
            else:
                bx, by = rect[0] + CARD_W - 22, rect[1] + 22
                if (p['x'] - bx) ** 2 + (p['y'] - by) ** 2 <= 14 ** 2:
                    self.dismiss(c)
        elif kind == 'dnd':
            self.mgr.toggle_dnd()
        elif kind == 'clear':
            self.clear_all()
        self._ensure_tick()

    def on_scroll(self, ctl, dx, dy):
        mx = max(0.0, self.content_h - self.view_h)
        self.scroll.t = clamp(self.scroll.t + dy * 64, 0, mx)
        self._ensure_tick()
        return True

    def on_key(self, ctl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    # ---------------------------------------------------------------- actions
    def dismiss(self, c, delay=0.0):
        if c.leaving:
            return
        c.leaving = True
        c.delay = (time.monotonic() - self.t0) + delay

    def clear_all(self):
        cards = [c for c in self.ordered() if not c.leaving]
        if not cards:
            return
        self.clearing = True
        base = time.monotonic() - self.t0
        for i, c in enumerate(cards):
            c.leaving = True
            c.delay = base + i * .045
        self._ensure_tick()

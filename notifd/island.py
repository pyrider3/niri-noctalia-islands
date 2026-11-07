"""Dynamic-island notifications: a black notch that grows out of the top screen edge.

Compact (icon + title + one line) -> expands on hover / critical (full text + actions).
Only the newest notification is shown; swipe up, click the cross or click the island to dismiss.
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
from gfx import THEME, Spring, clamp, rrect  # noqa: E402
from model import CRITICAL  # noqa: E402

PI = math.pi
WIN_W = 560
WIN_H = 230
CW, CH = 340, 56          # compact size
EW = 452                  # expanded width
HIDE_W, HIDE_H = 96, 10   # the "notch" it grows out of
FLARE = 16


def island_path(cr, cx, w, h, flare=FLARE, rb=26):
    """Rounded pill hanging from the top edge, with concave 'flares' where it joins the edge."""
    x = cx - w / 2
    rb = min(rb, h / 2, w / 2)
    fl = min(flare, h)
    cr.new_path()
    cr.move_to(x - fl, 0)
    cr.arc(x - fl, fl, fl, -PI / 2, 0)
    cr.line_to(x, h - rb)
    cr.arc_negative(x + rb, h - rb, rb, PI, PI / 2)
    cr.line_to(x + w - rb, h)
    cr.arc_negative(x + w - rb, h - rb, rb, PI / 2, 0)
    cr.line_to(x + w, fl)
    cr.arc(x + w + fl, fl, fl, PI, 3 * PI / 2)
    cr.close_path()


class Item:
    def __init__(self, n):
        self.n = n
        self.born = time.monotonic()
        self.total = n.seconds()
        self.remaining = self.total
        self.build()

    def build(self):
        n = self.n
        # compact
        self.c_title = gfx.make_layout(n.summary or '（无标题）', 13.5, True, width=CW - 54 - 76, lines=1)
        self.c_body = gfx.make_layout(gfx.strip_markup(n.body) or n.app, 11.5, width=CW - 54 - 76, lines=1)
        # expanded
        tx = 76
        tw = EW - tx - 28
        self.e_app = gfx.make_layout(n.app or '通知', 11, True, width=tw - 70, lines=1)
        self.e_title = gfx.make_layout(n.summary or '（无标题）', 15, True, width=tw, lines=2)
        y = 38 + gfx.text_size(self.e_title)[1]
        self.e_body = None
        if n.body.strip():
            self.e_body = gfx.make_layout(gfx.safe_markup(n.body), 12.5, width=tw, lines=3, markup=True)
            y += 4
            self.e_body_y = y
            y += gfx.text_size(self.e_body)[1]
        self.pills = []
        acts = [(k, l) for k, l in n.actions if k != 'default'][:3]
        if acts:
            y += 12
            px = tx
            for k, label in acts:
                lay = gfx.make_layout(label, 12, True, lines=1)
                w = gfx.text_size(lay)[0] + 30
                if px + w > EW - 24:
                    break
                self.pills.append(dict(key=k, lay=lay, x=px, y=y, w=w, h=30))
                px += w + 8
            y += 30
        self.eh = max(104, y + 20)
        self.default_action = any(k == 'default' for k, _ in n.actions)
        self.icon = None
        if n.image is not None:
            self.icon = gfx.pixbuf_surface(n.image, 44)
        if self.icon is None:
            self.icon = gfx.app_icon_surface(n, 44)


class IslandLayer:
    def __init__(self, app, on_action, on_closed):
        self.app = app
        self.on_action = on_action
        self.on_closed = on_closed
        self.item = None
        self.win = None
        self.tick_id = None
        self.last = None
        self.hover = False
        self.pointer = None
        self.press = None
        self.region_key = None
        self.w = Spring(HIDE_W, omega=30, zeta=.52)
        self.h = Spring(HIDE_H, omega=30, zeta=.52)
        self.ca = Spring(0, omega=20, zeta=1.0)       # content opacity
        self.exp = Spring(0, omega=28, zeta=.9)       # 0 compact .. 1 expanded
        self.lift = Spring(0, omega=34, zeta=.5)      # little bounce when something new arrives
        self.frame = 0

    # ------------------------------------------------------------------ API
    def ids(self):
        return {self.item.n.id} if self.item else set()

    def clear(self):
        self.item = None
        self.hover = False
        if self.win is not None:
            self.win.set_visible(False)
        self.region_key = None

    def shutdown(self):
        self.clear()
        if self.win is not None:
            self.win.destroy()
            self.win = None

    def show(self, n):
        self._ensure_window()
        if self.item is not None and self.item.n.id == n.id:
            self.item.n = n
            self.item.build()
            self.item.total = n.seconds()
            self.item.remaining = self.item.total
            self.item.born = time.monotonic()
        else:
            if self.item is not None:
                self.on_closed(self.item.n.id, 1)
            self.item = Item(n)
            self.ca.x = 0
        self.ca.t = 1
        self.lift.x = 1.0
        self.lift.t = 0
        self.win.present()
        self._ensure_tick()

    def close_id(self, nid, reason=3):
        if self.item is not None and self.item.n.id == nid:
            self._dismiss(reason)

    # --------------------------------------------------------------- window
    def _ensure_window(self):
        if self.win is not None:
            return
        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('notifd')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'notifd-island')
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
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
        drag.connect('drag-begin', self._on_drag_begin)
        drag.connect('drag-update', self._on_drag_update)
        drag.connect('drag-end', self._on_drag_end)
        da.add_controller(drag)
        click = Gtk.GestureClick()
        click.set_button(3)
        click.connect('pressed', lambda g, n, x, y: self._dismiss(2))
        da.add_controller(click)
        win.set_child(da)
        self.win, self.da = win, da

    # ------------------------------------------------------------ animation
    def _ensure_tick(self):
        if self.tick_id is None and self.win is not None:
            self.last = None
            self.tick_id = self.da.add_tick_callback(self._tick)

    def _expanded_wanted(self):
        it = self.item
        if it is None:
            return False
        if self.hover or self.press is not None:
            return True
        return it.n.urgency == CRITICAL and time.monotonic() - it.born < 6

    def _tick(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = (now - self.last) if self.last else 1 / 60
        self.last = now
        THEME.refresh()
        it = self.item
        if it is not None:
            want = self._expanded_wanted()
            self.exp.t = 1.0 if want else 0.0
            if it.total and not want:
                it.remaining -= dt
                if it.remaining <= 0:
                    self._dismiss(1)
                    it = self.item
        if it is not None:
            e = clamp(self.exp.x)
            self.w.t = CW + (EW - CW) * self.exp.t
            self.h.t = CH + (it.eh - CH) * self.exp.t
        else:
            self.w.t, self.h.t = HIDE_W, HIDE_H
            self.ca.t = 0
        for sp in (self.w, self.h, self.ca, self.exp, self.lift):
            sp.step(dt)
        self.frame += 1
        self.da.queue_draw()
        self._update_region()
        if self.item is None and self.h.x <= HIDE_H + .6 and self.ca.x < .02 and self.h.settled:
            self.win.set_visible(False)
            self.region_key = None
            self.tick_id = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        cx = WIN_W / 2
        w, h = self.w.x, self.h.x
        rect = (int(cx - w / 2 - FLARE), 0, int(w + 2 * FLARE), int(h) + 6) if self.item else None
        if rect == self.region_key:
            return
        self.region_key = rect
        surface.set_input_region(cairo.Region([cairo.RectangleInt(*rect)]) if rect else cairo.Region())

    # ----------------------------------------------------------------- draw
    def draw(self, area, cr, W, H):
        th = THEME
        it = self.item
        w, h = max(40.0, self.w.x), max(6.0, self.h.x)
        cx = W / 2
        bob = self.lift.x * 5          # a small drop when a notification lands
        cr.save()
        cr.translate(0, -bob * 0 + 0)
        gfx.shadow(cr, cx - w / 2, 0, w, h, 26, 1.2, dy=8)
        island_path(cr, cx, w, h, rb=min(34, h / 2))
        cr.set_source_rgb(0, 0, 0)
        cr.fill_preserve()
        cr.set_source_rgba(*th.text, .09)
        cr.set_line_width(1)
        cr.stroke()
        if it is not None and self.ca.x > .02:
            cr.save()
            island_path(cr, cx, w, h, rb=min(34, h / 2))
            cr.clip()
            e = clamp(self.exp.x)
            a = clamp(self.ca.x)
            left = cx - w / 2
            if e < .98:
                self._draw_compact(cr, it, left, a * (1 - e) ** 1.5)
            if e > .02:
                self._draw_expanded(cr, it, left, a * e ** 1.5)
            cr.restore()
        cr.restore()

    def _ring(self, cr, it, cx, cy, r, col):
        cr.set_line_width(2.2)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.arc(cx, cy, r, 0, gfx.TAU)
        cr.set_source_rgba(1, 1, 1, .12)
        cr.stroke()
        if it.total:
            frac = clamp(it.remaining / it.total)
            cr.arc(cx, cy, r, -PI / 2, -PI / 2 + gfx.TAU * frac)
            cr.set_source_rgb(*col)
            cr.stroke()

    def _icon(self, cr, it, cx, cy, size, col):
        age = time.monotonic() - it.born
        cr.save()
        cr.translate(cx, cy)
        if age < .9:
            p = 1 + .18 * math.exp(-age * 6) * math.sin(age * 20)
            cr.scale(p, p)
        if it.icon is not None:
            gfx.draw_surface_fit(cr, it.icon, 0, 0, size)
        else:
            lay = gfx.text_layout(gfx.initial(it.n.app or it.n.summary), size * .72, True)
            lw, lh = gfx.text_size(lay)
            gfx.draw_layout(cr, lay, -lw / 2, -lh / 2, (*col, 1))
        cr.restore()

    def _draw_compact(self, cr, it, left, alpha):
        th = THEME
        crit = it.n.urgency == CRITICAL
        col = th.danger if crit else gfx.avatar_colour(it.n.app or it.n.summary)
        cr.push_group()
        cy = CH / 2 + 1
        self._ring(cr, it, left + 32, cy, 19, th.danger if crit else th.accent)
        self._icon(cr, it, left + 32, cy, 26, col)
        gfx.draw_layout(cr, it.c_title, left + 58, 10, (1, 1, 1, 1))
        gfx.draw_layout(cr, it.c_body, left + 58, 30, (1, 1, 1, .58))
        # little equaliser on the right, lively for the first seconds
        t = time.monotonic() - it.born
        amp = clamp(1.3 - t / 6)
        for i in range(4):
            hh = 4 + (3 + 9 * abs(math.sin(t * 7 + i * 1.4))) * amp
            rrect(cr, left + CW - 34 + i * 6, cy - hh / 2, 3, hh, 1.5)
            cr.set_source_rgba(*(th.danger if crit else th.accent), .95)
            cr.fill()
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)

    def _draw_expanded(self, cr, it, left, alpha):
        th = THEME
        n = it.n
        crit = n.urgency == CRITICAL
        col = th.danger if crit else gfx.avatar_colour(n.app or n.summary)
        cr.push_group()
        self._ring(cr, it, left + 38, 46, 27, th.danger if crit else th.accent)
        self._icon(cr, it, left + 38, 46, 42, col)
        gfx.draw_layout(cr, it.e_app, left + 76, 18, (1, 1, 1, .55))
        t = gfx.text_layout(gfx.ago(n.ts), 11)
        gfx.draw_layout(cr, t, left + EW - 52 - gfx.text_size(t)[0], 18, (1, 1, 1, .45))
        gfx.draw_layout(cr, it.e_title, left + 76, 36, (1, 1, 1, 1))
        if it.e_body is not None:
            gfx.draw_layout(cr, it.e_body, left + 76, it.e_body_y, (1, 1, 1, .72))
        for i, p in enumerate(it.pills):
            px, py = left + p['x'], p['y']
            hot = self._pill_at() == i
            rrect(cr, px, py, p['w'], p['h'], p['h'] / 2)
            cr.set_source_rgba(1, 1, 1, .24 if hot else .13)
            cr.fill()
            gfx.draw_layout(cr, p['lay'], px + 15, py + (p['h'] - gfx.text_size(p['lay'])[1]) / 2, (1, 1, 1, .96))
        # close cross
        bx, by = left + EW - 24, 24
        cr.arc(bx, by, 11, 0, gfx.TAU)
        cr.set_source_rgba(1, 1, 1, .12)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, .8)
        cr.set_line_width(1.6)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(bx - 3.6, by - 3.6); cr.line_to(bx + 3.6, by + 3.6)
        cr.move_to(bx + 3.6, by - 3.6); cr.line_to(bx - 3.6, by + 3.6)
        cr.stroke()
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)

    # ---------------------------------------------------------------- input
    def _inside(self, x, y):
        cx = WIN_W / 2
        w, h = self.w.x, self.h.x
        return self.item is not None and cx - w / 2 - 4 <= x <= cx + w / 2 + 4 and 0 <= y <= h + 4

    def _pill_at(self):
        it = self.item
        if it is None or self.pointer is None or self.exp.x < .6:
            return -1
        left = WIN_W / 2 - self.w.x / 2
        px, py = self.pointer
        for i, p in enumerate(it.pills):
            if left + p['x'] <= px <= left + p['x'] + p['w'] and p['y'] <= py <= p['y'] + p['h']:
                return i
        return -1

    def _on_motion(self, ctl, x, y):
        self.pointer = (x, y)
        self.hover = self._inside(x, y)
        self._ensure_tick()

    def _on_leave(self, ctl):
        self.pointer = None
        self.hover = False

    def _on_drag_begin(self, g, x, y):
        self.press = dict(x=x, y=y, moved=False) if self._inside(x, y) else None

    def _on_drag_update(self, g, dx, dy):
        p = self.press
        if p and (abs(dy) > 6 or abs(dx) > 6):
            p['moved'] = True

    def _on_drag_end(self, g, dx, dy):
        p, self.press = self.press, None
        if not p or self.item is None:
            return
        if p['moved']:
            if dy < -28:
                self._dismiss(2)
            return
        it = self.item
        x, y = p['x'], p['y']
        if self.exp.x > .6:
            left = WIN_W / 2 - self.w.x / 2
            if (x - (left + EW - 24)) ** 2 + (y - 24) ** 2 <= 14 ** 2:
                self._dismiss(2)
                return
            i = self._pill_at()
            if i >= 0:
                self.on_action(it.n.id, it.pills[i]['key'])
                self._dismiss(2)
                return
        if it.default_action:
            self.on_action(it.n.id, 'default')
        self._dismiss(2)

    def _dismiss(self, reason):
        it = self.item
        if it is None:
            return
        self.item = None
        self.hover = False
        self.on_closed(it.n.id, reason)
        self._ensure_tick()

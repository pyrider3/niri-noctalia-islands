"""In-bar capsule notifications.

There is no popup: the bell widget in the bar stretches into a capsule that shows the icon, title and a
one-line summary (drawn by the bell plugin from ~/.local/state/notifd/current.json). Hovering it opens a small
detail card right under the bar, with the full text and the action buttons.
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
import model  # noqa: E402
from gfx import THEME, Spring, clamp, mix, rrect  # noqa: E402
from model import CRITICAL  # noqa: E402

CURRENT = model.STATE_DIR / 'current.json'
CURRENT_ICON = model.STATE_DIR / 'current-icon.png'

# Where the bell capsule sits on screen (distance from the right edge). The capsule grows to the left, so the
# detail card is right-aligned to the same edge. Measured on this desktop; change if the bar layout changes.
BELL_RIGHT = 359
POP_TOP = 40
STACK_RIGHT = 26   # cards sit at the screen's right edge (8px margin + shadow padding)
CARD_W = 344
PADX = 18
WIN_W = CARD_W + 2 * PADX
GRACE = .35


def _write_icon(n, item_icon):
    """Save the notification icon as a PNG for the bell widget (letter tile when there is none)."""
    try:
        if item_icon is not None:
            surf = item_icon
        else:
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
            c = cairo.Context(surf)
            col = gfx.avatar_colour(n.app or n.summary)
            g = cairo.LinearGradient(0, 0, 0, 64)
            g.add_color_stop_rgb(0, *mix(col, (1, 1, 1), .25))
            g.add_color_stop_rgb(1, *mix(col, (0, 0, 0), .18))
            gfx.rrect(c, 0, 0, 64, 64, 18)
            c.set_source(g)
            c.fill()
            lay = gfx.make_layout(gfx.initial(n.app or n.summary), 36, True)
            lw, lh = gfx.text_size(lay)
            gfx.draw_layout(c, lay, 32 - lw / 2, 32 - lh / 2, (1, 1, 1, 1))
        surf.write_to_png(str(CURRENT_ICON))
        return True
    except Exception:
        return False


class Item:
    def __init__(self, n, pills=True):
        self.with_pills = pills
        self.n = n
        self.born = time.monotonic()
        self.total = n.seconds()
        self.remaining = self.total
        self.build()

    def build(self):
        n = self.n
        tw = CARD_W - 36
        self.l_app = gfx.make_layout(n.app or '通知', 11, True, width=tw - 70, lines=1)
        self.l_sum = gfx.make_layout(n.summary or '（无标题）', 14.5, True, width=tw, lines=2)
        y = 38 + gfx.text_size(self.l_sum)[1] - 18
        self.sum_y = 36
        self.l_body = None
        if n.body.strip():
            self.l_body = gfx.make_layout(gfx.safe_markup(n.body), 12.5, width=tw, lines=4, markup=True)
            y += 4
            self.body_y = 36 + gfx.text_size(self.l_sum)[1] + 4
            y = self.body_y + gfx.text_size(self.l_body)[1]
        else:
            y = 36 + gfx.text_size(self.l_sum)[1]
        self.pills = []
        acts = [(k, l) for k, l in n.actions if k != 'default'][:3] if self.with_pills else []
        if acts:
            y += 12
            px = 18
            for k, label in acts:
                lay = gfx.make_layout(label, 12, True, lines=1)
                w = gfx.text_size(lay)[0] + 28
                if px + w > CARD_W - 18:
                    break
                self.pills.append(dict(key=k, lay=lay, x=px, y=y, w=w, h=30))
                px += w + 8
            y += 30
        self.h = y + 18
        self.default_action = any(k == 'default' for k, _ in n.actions)
        self.icon = None
        if not self.with_pills:
            return          # stack cards draw no icon
        if n.image is not None:
            self.icon = gfx.pixbuf_surface(n.image, 64)
        if self.icon is None:
            self.icon = gfx.app_icon_surface(n, 64)


class CapsuleLayer:
    def __init__(self, app, on_action, on_closed):
        self.app = app
        self.on_action = on_action
        self.on_closed = on_closed
        self.item = None
        self.bell_hover = False
        self.popup_hover = False
        self.last_hover = 0.0
        self.win = None
        self.press = None
        self.pointer = None
        self.show_pop = Spring(0, omega=30, zeta=.62)
        self.tick_id = None
        self.frame_tick = None
        self._tlast = time.monotonic()
        self._fl = None
        self.region_key = None
        self.win_h = 160
        self.mgr = None
        self.stack = None
        self._write_inactive()
        GLib.timeout_add(800, self._prewarm)

    def _prewarm(self):
        if self.mgr is not None and self.stack is None:
            from stack import Stack
            self.stack = Stack(self.app, self.mgr, lambda n: Item(n, pills=False), STACK_RIGHT, POP_TOP, self.on_closed)
            self.stack._ensure_window()
        return False

    # ------------------------------------------------------------------ API
    def ids(self):
        return {self.item.n.id} if self.item else set()

    def clear(self):
        self.item = None
        self.bell_hover = self.popup_hover = False
        self._write_inactive()
        if self.win is not None:
            self.win.set_visible(False)
        self.region_key = None

    def shutdown(self):
        if self.stack is not None:
            self.stack.shutdown()
            self.stack = None
        self.clear()
        if self.win is not None:
            self.win.destroy()
            self.win = None
        if self.tick_id is not None:
            GLib.source_remove(self.tick_id)
            self.tick_id = None

    def show(self, n):
        if self.stack is not None and self.stack.is_open:
            self.stack.refresh()
            return
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
        _write_icon(n, self.item.icon)
        self._publish()
        if self.tick_id is None:
            self._tlast = time.monotonic()
            self.tick_id = GLib.timeout_add(33, self._timer)

    def close_id(self, nid, reason=3):
        if self.item is not None and self.item.n.id == nid:
            self._dismiss(reason)

    # --------------------------------------------------- bell widget events
    def set_bell_hover(self, entered):
        self.bell_hover = bool(entered)
        if not entered:
            self.last_hover = time.monotonic()
        self._ensure_frames()

    def handle_bell_click(self):
        """The bell opens/closes a stack of floating cards instead of the big centre panel."""
        if self.mgr is None:
            return False
        if self.stack is None:
            from stack import Stack
            self.stack = Stack(self.app, self.mgr, lambda n: Item(n, pills=False), STACK_RIGHT, POP_TOP, self.on_closed)
        if self.item is not None and not self.stack.is_open:
            self._dismiss(2)
        self.stack.toggle()
        return True

    # ------------------------------------------------------------- publishing
    def _write_inactive(self):
        try:
            model.write_json(CURRENT, dict(active=False, t=time.time()))
        except OSError:
            pass

    def _hovered(self):
        return self.bell_hover or self.popup_hover

    def _publish(self):
        it = self.item
        if it is None:
            self._write_inactive()
            return
        n = it.n
        try:
            model.write_json(CURRENT, dict(
                active=True, id=n.id, app=n.app, summary=n.summary, body=gfx.strip_markup(n.body),
                urgency=n.urgency, total=it.total, remaining=it.remaining, paused=bool(self._hovered()),
                t=time.time(), icon=str(CURRENT_ICON), born=time.time() - (time.monotonic() - it.born)))
        except OSError:
            pass

    def _timer(self):
        now = time.monotonic()
        dt = now - self._tlast
        self._tlast = now
        it = self.item
        if it is None:
            self.tick_id = None
            return False
        if not self._hovered() and it.total:
            it.remaining -= dt
            if it.remaining <= 0:
                self._dismiss(1)
                return self.item is not None
        self._publish()
        return True

    def _dismiss(self, reason):
        it = self.item
        if it is None:
            return
        self.item = None
        self.bell_hover = self.popup_hover = False
        self._write_inactive()
        self.on_closed(it.n.id, reason)
        self._ensure_frames()

    # --------------------------------------------------------- detail popup
    def _ensure_window(self):
        if self.win is not None:
            return
        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('notifd')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'notifd-capsule')
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.RIGHT, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_margin(win, LS.Edge.TOP, POP_TOP)
        LS.set_margin(win, LS.Edge.RIGHT, BELL_RIGHT - PADX)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        win.set_default_size(WIN_W, 160)
        da = Gtk.DrawingArea()
        da.set_content_width(WIN_W)
        da.set_content_height(160)
        da.set_draw_func(self.draw)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_leave)
        da.add_controller(motion)
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect('drag-begin', lambda g, x, y: setattr(self, 'press', (x, y)))
        drag.connect('drag-end', self._on_drag_end)
        da.add_controller(drag)
        win.set_child(da)
        self.win, self.da = win, da

    def _ensure_frames(self):
        want = self.item is not None and (self._hovered() or time.monotonic() - self.last_hover < GRACE)
        if want or not self.show_pop.settled or self.show_pop.x > .01:
            if self.win is None and want:
                self._ensure_window()
            if self.win is not None and self.frame_tick is None:
                self._fl = None
                self.win.present()
                self.frame_tick = self.da.add_tick_callback(self._frame)

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        dt = min(.05, now - self._fl) if getattr(self, '_fl', None) else 1 / 60
        self._fl = now
        THEME.refresh()
        want = self.item is not None and (self._hovered() or time.monotonic() - self.last_hover < GRACE)
        self.show_pop.t = 1.0 if want else 0.0
        self.show_pop.step(dt)
        it = self.item
        if it is not None:
            need = int(it.h + 56)
            need = (need + 19) // 20 * 20
            if need != self.win_h:
                self.win_h = need
                self.da.set_content_height(need)
        self.da.queue_draw()
        self._update_region()
        if not want and self.show_pop.x < .01 and self.show_pop.settled:
            self.win.set_visible(False)
            self.frame_tick = None
            self.popup_hover = False
            self.region_key = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        it = self.item
        rect = (PADX - 4, 0, CARD_W + 8, int(it.h) + 14) if (it is not None and self.show_pop.x > .3) else None
        if rect == self.region_key:
            return
        self.region_key = rect
        surface.set_input_region(cairo.Region([cairo.RectangleInt(*rect)]) if rect else cairo.Region())

    def draw(self, area, cr, W, H):
        it = self.item
        a = clamp(self.show_pop.x)
        if it is None or a < .01:
            return
        th = THEME
        n = it.n
        crit = n.urgency == CRITICAL
        w, h = CARD_W, it.h
        x0 = PADX
        slide = (1 - self.show_pop.x) * -14
        y0 = 6 + slide
        sc = .94 + .06 * min(1.08, self.show_pop.x)
        cr.save()
        cx = x0 + w - 30          # grow out of the bell side
        cr.translate(cx, 0)
        cr.scale(sc, sc)
        cr.translate(-cx, 0)
        cr.push_group()
        gfx.shadow(cr, x0, y0, w, h, 22, 1.3)
        rrect(cr, x0, y0, w, h, 22)
        cr.set_source_rgba(*mix(th.bg, th.text, .07), .98)
        cr.fill_preserve()
        cr.set_source_rgba(*(th.danger if crit else th.text), .40 if crit else .12)
        cr.set_line_width(1)
        cr.stroke()
        gfx.draw_layout(cr, it.l_app, x0 + 18, y0 + 14, (*th.text, .55))
        t = gfx.text_layout(gfx.ago(n.ts), 11)
        gfx.draw_layout(cr, t, x0 + w - 18 - gfx.text_size(t)[0], y0 + 14, (*th.text, .45))
        gfx.draw_layout(cr, it.l_sum, x0 + 18, y0 + it.sum_y, (*th.text, 1))
        if it.l_body is not None:
            gfx.draw_layout(cr, it.l_body, x0 + 18, y0 + it.body_y, (*th.text, .72))
        for i, p in enumerate(it.pills):
            px, py = x0 + p['x'], y0 + p['y']
            hot = self._pill_at() == i
            rrect(cr, px, py, p['w'], p['h'], p['h'] / 2)
            cr.set_source_rgba(*th.accent, .32 if hot else .18)
            cr.fill()
            gfx.draw_layout(cr, p['lay'], px + 14, py + (p['h'] - gfx.text_size(p['lay'])[1]) / 2, (*th.accent, 1))
        cr.pop_group_to_source()
        cr.paint_with_alpha(a)
        cr.restore()

    # ---------------------------------------------------------------- input
    def _pill_at(self):
        it = self.item
        if it is None or self.pointer is None:
            return -1
        px, py = self.pointer
        for i, p in enumerate(it.pills):
            if PADX + p['x'] <= px <= PADX + p['x'] + p['w'] and 6 + p['y'] <= py <= 6 + p['y'] + p['h']:
                return i
        return -1

    def _on_motion(self, ctl, x, y):
        self.pointer = (x, y)
        self.popup_hover = True
        self.last_hover = time.monotonic()

    def _on_leave(self, ctl):
        self.pointer = None
        self.popup_hover = False
        self.last_hover = time.monotonic()

    def _on_drag_end(self, g, dx, dy):
        p, self.press = self.press, None
        it = self.item
        if it is None or p is None or abs(dx) > 8 or abs(dy) > 8:
            return
        i = self._pill_at()
        if i >= 0:
            self.on_action(it.n.id, it.pills[i]['key'])
            self._dismiss(2)
            return
        if it.default_action:
            self.on_action(it.n.id, 'default')
        self._dismiss(2)

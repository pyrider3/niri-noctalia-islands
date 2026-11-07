"""Animated toast popups (one layer-shell window, everything drawn with cairo)."""
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
from gfx import THEME, Spring, clamp, lerp, mix, rrect  # noqa: E402
from model import CRITICAL, LOW  # noqa: E402

CARD_W = 360
WIN_W = 412
PADX = 18
TOP_MARGIN = 42      # bar capsules end at ~33 px; margins count from the screen edge
GAP = 10
MAX_VISIBLE = 5
RADIUS = 22


class Toast:
    W = CARD_W

    def __init__(self, n):
        self.n = n
        self.born = time.monotonic()
        self.build()
        self.x = Spring(self.W + 90, omega=23, zeta=.5)       # slides in from the right with a bounce
        self.x.t = 0
        self.y = Spring(0, omega=26, zeta=.8)
        self.alpha = Spring(0, omega=22, zeta=1.0)
        self.alpha.t = 1
        self.scale = Spring(.88, omega=26, zeta=.55)
        self.scale.t = 1
        self.hover = Spring(0, omega=28, zeta=1.0)
        self.pill_hover = -1
        self.state = 'in'                 # in | out
        self.dragging = False
        self.total = n.seconds()
        self.remaining = self.total
        self.placed = False
        self.closed_reason = None

    # --------------------------------------------------------------- layout
    def build(self):
        n = self.n
        pad, icon = 14, 44
        self.tx = pad + icon + 12
        tw = self.W - self.tx - pad
        self.l_app = gfx.make_layout(n.app or '通知', 11, True, width=tw - 76, lines=1)
        self.l_sum = gfx.make_layout(n.summary or '（无标题）', 14, True, width=tw, lines=2)
        y = pad + 17
        self.sum_y = y
        y += gfx.text_size(self.l_sum)[1]
        self.l_body = None
        if n.body.strip():
            self.l_body = gfx.make_layout(gfx.safe_markup(n.body), 12.5, width=tw, lines=3, markup=True)
            y += 3
            self.body_y = y
            y += gfx.text_size(self.l_body)[1]
        self.pills = []
        acts = [(k, l) for k, l in n.actions if k != 'default'][:3]
        if acts:
            y += 10
            px = self.tx
            for k, label in acts:
                lay = gfx.make_layout(label, 12, True, lines=1)
                w = gfx.text_size(lay)[0] + 26
                if px + w > self.W - pad:
                    break
                self.pills.append(dict(key=k, lay=lay, x=px, y=y, w=w, h=28))
                px += w + 8
            y += 28
        self.h = max(pad * 2 + icon, y + pad)
        self.default_action = any(k == 'default' for k, _ in n.actions)
        self.icon_surf = None
        if n.image is not None:
            self.icon_surf = gfx.pixbuf_surface(n.image, 32)
        if self.icon_surf is None:
            self.icon_surf = gfx.app_icon_surface(n, 32)

    def rect(self):
        return PADX + self.x.x, self.y.x + 0.0, self.W, self.h

    # ----------------------------------------------------------------- draw
    def draw(self, cr, top):
        th = THEME
        n = self.n
        x0, y0 = PADX + self.x.x, top + self.y.x
        w, h = self.W, self.h
        age = time.monotonic() - self.born
        hv = clamp(self.hover.x)
        alpha = clamp(self.alpha.x)
        if alpha <= .005:
            return
        s = self.scale.x * (1 + .012 * hv)
        cx, cy = x0 + w / 2, y0 + h / 2
        cr.save()
        cr.translate(cx, cy)
        cr.scale(s, s)
        cr.translate(-cx, -cy)
        cr.push_group()
        crit = n.urgency == CRITICAL
        gfx.shadow(cr, x0, y0, w, h, RADIUS, 1.0 + hv * .5)
        rrect(cr, x0, y0, w, h, RADIUS)
        base = mix(th.card, th.card_hi, hv)
        cr.set_source_rgba(*base, .97)
        cr.fill_preserve()
        if crit:
            pulse = .55 + .45 * math.sin(age * 4.2)
            cr.set_source_rgba(*th.danger, .35 + .5 * pulse)
            cr.set_line_width(1.8)
        else:
            cr.set_source_rgba(*th.text, .10 + .06 * hv)
            cr.set_line_width(1)
        cr.stroke()
        # clipped extras: countdown line + urgency wash
        cr.save()
        rrect(cr, x0, y0, w, h, RADIUS)
        cr.clip()
        if crit:
            g = cairo.LinearGradient(x0, 0, x0 + 120, 0)
            g.add_color_stop_rgba(0, *th.danger, .22)
            g.add_color_stop_rgba(1, *th.danger, 0)
            cr.set_source(g)
            cr.rectangle(x0, y0, 120, h)
            cr.fill()
        if self.total:
            frac = clamp(self.remaining / self.total)
            col = th.danger if crit else th.accent
            cr.set_source_rgba(*col, .85)
            cr.rectangle(x0, y0 + h - 3, w * frac, 3)
            cr.fill()
        cr.restore()
        # ---- icon with wiggle + ripple on arrival
        ix, iy = x0 + 14 + 22, y0 + 14 + 22
        col = th.danger if crit else gfx.avatar_colour(n.app or n.summary)
        if age < 1.1:
            p = age / 1.1
            cr.arc(ix, iy, 22 + 26 * p, 0, gfx.TAU)
            cr.set_source_rgba(*(th.danger if crit else th.accent), .45 * (1 - p) ** 2)
            cr.set_line_width(2.2 * (1 - p) + .4)
            cr.stroke()
        cr.save()
        cr.translate(ix, iy)
        if age < 1.2:
            cr.rotate(math.sin(age * 24) * .34 * math.exp(-age * 5.2))
            sc = 1 + .12 * math.exp(-age * 7) * math.sin(age * 18 + 1.2)
            cr.scale(sc, sc)
        cr.arc(0, 0, 22, 0, gfx.TAU)
        cr.set_source_rgba(*col, .20)
        cr.fill()
        if self.icon_surf is not None:
            gfx.draw_surface_fit(cr, self.icon_surf, 0, 0, 28)
        else:
            lay = gfx.text_layout(gfx.initial(n.app or n.summary), 20, True)
            lw, lh = gfx.text_size(lay)
            gfx.draw_layout(cr, lay, -lw / 2, -lh / 2, (*col, 1))
        cr.restore()
        # ---- texts
        tx = x0 + self.tx
        gfx.draw_layout(cr, self.l_app, tx, y0 + 14, (*th.text, .58))
        lay_t = gfx.text_layout(gfx.ago(n.ts), 11)
        tw_, _ = gfx.text_size(lay_t)
        gfx.draw_layout(cr, lay_t, x0 + w - 14 - tw_, y0 + 14, (*th.text, .5 * (1 - hv)))
        gfx.draw_layout(cr, self.l_sum, tx, y0 + self.sum_y, (*th.text, .98))
        if self.l_body is not None:
            gfx.draw_layout(cr, self.l_body, tx, y0 + self.body_y, (*th.text, .74))
        # ---- action pills
        for i, p in enumerate(self.pills):
            px, py = x0 + p['x'], y0 + p['y']
            hot = self.pill_hover == i
            rrect(cr, px, py, p['w'], p['h'], p['h'] / 2)
            cr.set_source_rgba(*th.accent, .30 if hot else .16)
            cr.fill()
            gfx.draw_layout(cr, p['lay'], px + 13, py + (p['h'] - gfx.text_size(p['lay'])[1]) / 2, (*th.accent, 1))
        # ---- close button (fades in on hover)
        if hv > .02:
            bx, by = x0 + w - 25, y0 + 25
            cr.arc(bx, by, 11, 0, gfx.TAU)
            cr.set_source_rgba(*th.text, .14 * hv)
            cr.fill()
            cr.set_source_rgba(*th.text, .85 * hv)
            cr.set_line_width(1.6)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(bx - 3.6, by - 3.6); cr.line_to(bx + 3.6, by + 3.6)
            cr.move_to(bx + 3.6, by - 3.6); cr.line_to(bx - 3.6, by + 3.6)
            cr.stroke()
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)
        cr.restore()

    # ------------------------------------------------------------------ hit
    def close_hit(self, px, py):
        x0, y0 = PADX + self.x.x, self.y.x
        return self.hover.x > .3 and (px - (x0 + self.W - 25)) ** 2 + (py - (y0 + 25)) ** 2 <= 13 ** 2

    def pill_at(self, px, py):
        x0, y0 = PADX + self.x.x, self.y.x
        for i, p in enumerate(self.pills):
            if x0 + p['x'] <= px <= x0 + p['x'] + p['w'] and y0 + p['y'] <= py <= y0 + p['y'] + p['h']:
                return i
        return -1


class FrostToast(Toast):
    """Light, frosted-glass card with a big icon (iOS / macOS style)."""
    W = 372
    PAD = 16
    ICON = 48

    def build(self):
        n = self.n
        pad, icon = self.PAD, self.ICON
        self.tx = pad + icon + 14
        tw = self.W - self.tx - pad
        self.l_app = gfx.make_layout(n.app or '通知', 11, True, width=tw - 60, lines=1)
        self.l_sum = gfx.make_layout(n.summary or '（无标题）', 14.5, True, width=tw, lines=2)
        y = pad + 17
        self.sum_y = y
        y += gfx.text_size(self.l_sum)[1]
        self.l_body = None
        if n.body.strip():
            self.l_body = gfx.make_layout(gfx.safe_markup(n.body), 12.5, width=tw, lines=3, markup=True)
            y += 3
            self.body_y = y
            y += gfx.text_size(self.l_body)[1]
        self.pills = []
        acts = [(k, l) for k, l in n.actions if k != 'default'][:3]
        if acts:
            y += 10
            px = self.tx
            for k, label in acts:
                lay = gfx.make_layout(label, 12, True, lines=1)
                w = gfx.text_size(lay)[0] + 28
                if px + w > self.W - pad:
                    break
                self.pills.append(dict(key=k, lay=lay, x=px, y=y, w=w, h=28))
                px += w + 8
            y += 28
        self.h = max(pad * 2 + icon + 4, y + pad)
        self.default_action = any(k == 'default' for k, _ in n.actions)
        self.icon_surf = None
        if n.image is not None:
            self.icon_surf = gfx.pixbuf_surface(n.image, 48)
        if self.icon_surf is None:
            self.icon_surf = gfx.app_icon_surface(n, 48)

    def draw(self, cr, top):
        th = THEME
        n = self.n
        x0, y0 = PADX + self.x.x, top + self.y.x
        w, h = self.W, self.h
        age = time.monotonic() - self.born
        hv = clamp(self.hover.x)
        alpha = clamp(self.alpha.x)
        if alpha <= .005:
            return
        light = (.2126 * th.bg[0] + .7152 * th.bg[1] + .0722 * th.bg[2]) < .5
        ink = (.08, .08, .12) if light else th.text
        s = self.scale.x * (1 + .012 * hv)
        cx, cy = x0 + w / 2, y0 + h / 2
        cr.save()
        cr.translate(cx, cy)
        cr.scale(s, s)
        cr.translate(-cx, -cy)
        cr.push_group()
        crit = n.urgency == CRITICAL
        R = 24
        gfx.shadow(cr, x0, y0, w, h, R, 1.6 + hv * .6, dy=9)
        rrect(cr, x0, y0, w, h, R)
        if light:
            g = cairo.LinearGradient(0, y0, 0, y0 + h)
            g.add_color_stop_rgba(0, 1, 1, 1, .95)
            g.add_color_stop_rgba(1, .92, .93, .97, .93)
            cr.set_source(g)
        else:
            cr.set_source_rgba(*mix(th.bg, th.text, .10 + .04 * hv), .94)
        cr.fill_preserve()
        if crit:
            cr.set_source_rgba(*th.danger, .45 + .4 * (.5 + .5 * math.sin(age * 4.2)))
            cr.set_line_width(1.8)
        else:
            cr.set_source_rgba(1, 1, 1, .75) if light else cr.set_source_rgba(*th.text, .12)
            cr.set_line_width(1)
        cr.stroke()
        # thin countdown line along the bottom edge
        if self.total:
            cr.save()
            rrect(cr, x0, y0, w, h, R)
            cr.clip()
            frac = clamp(self.remaining / self.total)
            cr.set_source_rgba(*(th.danger if crit else ink), .20)
            cr.rectangle(x0, y0 + h - 2.5, w * frac, 2.5)
            cr.fill()
            cr.restore()
        # ---- icon sits straight on the card: arrival pop, no tinted backing
        ix, iy = x0 + self.PAD + self.ICON / 2, y0 + self.PAD + self.ICON / 2
        cr.save()
        cr.translate(ix, iy)
        if age < 1.0:
            pop = 1 + .16 * math.exp(-age * 6) * math.sin(age * 20 + .9)
            cr.scale(pop, pop)
            cr.rotate(math.sin(age * 22) * .14 * math.exp(-age * 5))
        cr.arc(0, 3, self.ICON / 2 - 3, 0, gfx.TAU)
        cr.set_source_rgba(0, 0, 0, .12 if light else .25)
        cr.fill()
        if self.icon_surf is not None:
            gfx.draw_surface_fit(cr, self.icon_surf, 0, 0, self.ICON)
        else:
            col = th.danger if crit else gfx.avatar_colour(n.app or n.summary)
            gg = cairo.LinearGradient(0, -self.ICON / 2, 0, self.ICON / 2)
            gg.add_color_stop_rgb(0, *mix(col, (1, 1, 1), .25))
            gg.add_color_stop_rgb(1, *mix(col, (0, 0, 0), .18))
            rrect(cr, -self.ICON / 2, -self.ICON / 2, self.ICON, self.ICON, 13)
            cr.set_source(gg)
            cr.fill()
            lay = gfx.text_layout(gfx.initial(n.app or n.summary), 22, True)
            lw, lh = gfx.text_size(lay)
            gfx.draw_layout(cr, lay, -lw / 2, -lh / 2, (1, 1, 1, .98))
        cr.restore()
        if crit:
            cr.arc(x0 + self.PAD + self.ICON - 3, y0 + self.PAD + 4, 5.5, 0, gfx.TAU)
            cr.set_source_rgb(*th.danger)
            cr.fill()
        # ---- texts
        tx = x0 + self.tx
        gfx.draw_layout(cr, self.l_app, tx, y0 + 14, (*ink, .5))
        lay_t = gfx.text_layout(gfx.ago(n.ts), 11)
        tw_, _ = gfx.text_size(lay_t)
        gfx.draw_layout(cr, lay_t, x0 + w - 16 - tw_, y0 + 14, (*ink, .4 * (1 - hv)))
        gfx.draw_layout(cr, self.l_sum, tx, y0 + self.sum_y, (*ink, 1))
        if self.l_body is not None:
            gfx.draw_layout(cr, self.l_body, tx, y0 + self.body_y, (*ink, .66))
        # ---- action pills
        accent = (.12, .36, .80) if light else th.accent
        for i, p in enumerate(self.pills):
            px, py = x0 + p['x'], y0 + p['y']
            hot = self.pill_hover == i
            rrect(cr, px, py, p['w'], p['h'], p['h'] / 2)
            cr.set_source_rgba(*ink, .14 if hot else .07)
            cr.fill()
            gfx.draw_layout(cr, p['lay'], px + 14, py + (p['h'] - gfx.text_size(p['lay'])[1]) / 2, (*accent, 1))
        # ---- close button on hover
        if hv > .02:
            bx, by = x0 + w - 26, y0 + 26
            cr.arc(bx, by, 11, 0, gfx.TAU)
            cr.set_source_rgba(*ink, .10 * hv)
            cr.fill()
            cr.set_source_rgba(*ink, .7 * hv)
            cr.set_line_width(1.6)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(bx - 3.6, by - 3.6); cr.line_to(bx + 3.6, by + 3.6)
            cr.move_to(bx + 3.6, by - 3.6); cr.line_to(bx - 3.6, by + 3.6)
            cr.stroke()
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)
        cr.restore()

    def close_hit(self, px, py):
        x0, y0 = PADX + self.x.x, self.y.x
        return self.hover.x > .3 and (px - (x0 + self.W - 26)) ** 2 + (py - (y0 + 26)) ** 2 <= 13 ** 2


class ToastLayer:
    def __init__(self, app, on_action, on_closed, style='card'):
        self.app = app
        self.style = style
        self.on_action = on_action
        self.on_closed = on_closed
        self.toasts = []
        self.pointer = None
        self.tick_id = None
        self.last = None
        self.press = None
        self.win = None
        self.region_key = None

    # ---------------------------------------------------------------- window
    def _ensure_window(self):
        if self.win is not None:
            return
        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('notifd')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'notifd-toasts')
        for edge in (LS.Edge.TOP, LS.Edge.RIGHT):
            LS.set_anchor(win, edge, True)
        LS.set_exclusive_zone(win, -1)      # ignore the bar's reserved space, so the margin is exact
        LS.set_margin(win, LS.Edge.TOP, TOP_MARGIN)
        LS.set_margin(win, LS.Edge.RIGHT, 4)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        win.set_default_size(WIN_W, 120)
        da = Gtk.DrawingArea()
        da.set_content_width(WIN_W)
        da.set_content_height(120)
        da.set_draw_func(self.draw)
        self.win_h = 120
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self.on_motion)
        motion.connect('leave', self.on_leave)
        da.add_controller(motion)
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect('drag-begin', self.on_drag_begin)
        drag.connect('drag-update', self.on_drag_update)
        drag.connect('drag-end', self.on_drag_end)
        da.add_controller(drag)
        click = Gtk.GestureClick()
        click.set_button(3)
        click.connect('pressed', self.on_right_click)
        da.add_controller(click)
        win.set_child(da)
        self.win, self.da = win, da

    # ------------------------------------------------------------- presenter API
    def ids(self):
        return {t.n.id for t in self.toasts}

    def clear(self):
        """Drop everything on screen without sending close signals (used when the style changes)."""
        self.toasts = []
        self.pointer = None
        self.press = None
        if self.win is not None:
            self.win.set_visible(False)
        self.region_key = None

    def shutdown(self):
        self.clear()
        if self.win is not None:
            self.win.destroy()
            self.win = None

    # ------------------------------------------------------------- lifecycle
    def show(self, n):
        self._ensure_window()
        for t in self.toasts:
            if t.n.id == n.id and t.state == 'in':
                t.n = n
                t.build()
                t.total = n.seconds()
                t.remaining = t.total
                t.born = time.monotonic()
                t.scale.x = 1.05          # little kick so the update is noticed
                self._ensure_tick()
                return
        t = (FrostToast if self.style == 'frost' else Toast)(n)
        self.toasts.insert(0, t)
        live = [x for x in self.toasts if x.state == 'in']
        while len(live) > MAX_VISIBLE:
            self.dismiss(live.pop(), 1)
        self._layout(initial=t)
        self.win.present()
        self._ensure_tick()

    def close_id(self, nid, reason=3):
        for t in self.toasts:
            if t.n.id == nid and t.state == 'in':
                self.dismiss(t, reason)

    def dismiss(self, t, reason, fling=False):
        if t.state == 'out':
            return
        t.state = 'out'
        t.closed_reason = reason
        t.x.omega, t.x.zeta = (16, 1.0)
        t.x.t = t.W + 120
        t.alpha.omega = 14
        t.alpha.t = 0
        self.on_closed(t.n.id, reason)
        self._ensure_tick()

    # ------------------------------------------------------------- animation
    def _layout(self, initial=None):
        y = 0.0
        for t in self.toasts:
            if t.state == 'out':
                continue
            t.y.t = y
            if not t.placed:
                t.y.snap(y)
                t.placed = True
            y += t.h + GAP

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
        # full 60 fps only while something is really moving; slow pulses and countdowns need ~20 fps
        if self._moving() or self._frame % 3 == 0:
            self.da.queue_draw()
        self._update_region()
        self._fit_height()
        if not self.toasts:
            self.tick_id = None
            self.win.set_visible(False)
            self.region_key = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _hovered(self):
        if self.pointer is None:
            return None
        px, py = self.pointer
        for t in self.toasts:
            if t.state == 'out':
                continue
            x, y, w, h = t.rect()
            if x <= px <= x + w and y <= py <= y + h:
                return t
        return None

    def _step(self, dt):
        hot = self._hovered()
        for t in list(self.toasts):
            t.hover.t = 1.0 if (t is hot or t.dragging) else 0.0
            if t is hot and self.pointer:
                t.pill_hover = t.pill_at(*self.pointer)
            else:
                t.pill_hover = -1
            if t.state == 'in' and t.total and t is not hot and not t.dragging:
                t.remaining -= dt
                if t.remaining <= 0:
                    self.dismiss(t, 1)
            for sp in (t.x, t.y, t.alpha, t.scale, t.hover):
                sp.step(dt)
            if t.state == 'out' and t.alpha.x < .02:
                self.toasts.remove(t)
        self._layout()

    def _moving(self):
        if self.press or self.pointer is not None:
            return True
        now = time.monotonic()
        for t in self.toasts:
            if now - t.born < 1.3 or t.state == 'out':
                return True
            if any(not sp.settled for sp in (t.x, t.y, t.alpha, t.scale, t.hover)):
                return True
        return False

    def _fit_height(self):
        """The window is only as tall as the toast stack, so every frame redraws few pixels."""
        need = 120
        for t in self.toasts:
            need = max(need, int(t.y.x + t.h) + 44)
        need = (need + 19) // 20 * 20
        if need != self.win_h:
            self.win_h = need
            self.da.set_content_height(need)

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        rects = []
        for t in self.toasts:
            if t.state == 'out':
                continue
            x, y, w, h = t.rect()
            rects.append((int(x) - 4, int(y + TOP_MARGIN * 0) - 4, int(w) + 8, int(h) + 8))
        key = tuple(rects)
        if key == self.region_key:
            return
        self.region_key = key
        region = cairo.Region([cairo.RectangleInt(*r) for r in rects]) if rects else cairo.Region()
        surface.set_input_region(region)

    # ------------------------------------------------------------------ draw
    def draw(self, area, cr, w, h):
        for t in reversed(self.toasts):
            t.draw(cr, 0)

    # --------------------------------------------------------------- pointer
    def on_motion(self, ctl, x, y):
        self.pointer = (x, y)
        self._ensure_tick()

    def on_leave(self, ctl):
        self.pointer = None

    def _toast_at(self, x, y):
        for t in self.toasts:
            if t.state == 'out':
                continue
            rx, ry, rw, rh = t.rect()
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return t
        return None

    def on_drag_begin(self, g, x, y):
        t = self._toast_at(x, y)
        self.press = dict(t=t, x=x, y=y, moved=False, base=0.0) if t else None
        if t:
            self.pointer = (x, y)

    def on_drag_update(self, g, dx, dy):
        p = self.press
        if not p:
            return
        t = p['t']
        if abs(dx) > 6 or p['moved']:
            p['moved'] = True
            t.dragging = True
            t.x.snap(max(-30.0, dx))
            t.x.t = t.x.x
            t.alpha.t = clamp(1 - max(0, dx) / 260)
            t.alpha.x = t.alpha.t
            self._ensure_tick()

    def on_drag_end(self, g, dx, dy):
        p, self.press = self.press, None
        if not p:
            return
        t = p['t']
        if p['moved']:
            t.dragging = False
            if dx > 110:
                self.dismiss(t, 2)
            else:
                t.x.omega, t.x.zeta = 30, .55
                t.x.t = 0
                t.alpha.t = 1
        else:
            px, py = p['x'], p['y']
            if t.close_hit(px, py):
                self.dismiss(t, 2)
                return
            i = t.pill_at(px, py)
            if i >= 0:
                self.on_action(t.n.id, t.pills[i]['key'])
                self.dismiss(t, 2)
                return
            if t.default_action:
                self.on_action(t.n.id, 'default')
            self.dismiss(t, 2)
        self._ensure_tick()

    def on_right_click(self, g, n_press, x, y):
        t = self._toast_at(x, y)
        if t:
            self.dismiss(t, 2)

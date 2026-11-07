"""A small cairo UI toolkit for the settings island: rows with springs, groups, scrolling, page transitions.

Everything is drawn live from declarative rows; clickable areas are collected as 'zones' while drawing.
"""
import math
import time

import cairo

import gfx
from clock_island import dl, ease_back
from gfx import Spring, clamp, lerp, rrect

ROW_H = 60.0
PAD = 20.0


def tx(txt, a):
    return (*txt, a)


class Row:
    h = ROW_H
    kind = 'row'

    def __init__(self):
        self.sp = {}          # named springs

    def spring(self, name, value, omega=24, zeta=.6):
        s = self.sp.get(name)
        if s is None:
            s = self.sp[name] = Spring(value, omega=omega, zeta=zeta)
        return s

    def moving(self):
        return any(not s.settled for s in self.sp.values())

    def step(self, dt):
        for s in self.sp.values():
            s.step(dt)

    # to override
    def draw(self, ui, cr, x, y, w):
        pass

    def title_block(self, ui, cr, x, y, title, sub, w=None):
        dl(cr, gfx.make_layout(title, 15, True, width=w, lines=1) if w else gfx.text_layout(title, 15, True), x, y + (10 if sub else 20), (*ui.txt, 1))
        if sub:
            dl(cr, gfx.make_layout(sub, 12, False, width=w or 420, lines=1), x, y + 32, (*ui.txt, .5))


class Section(Row):
    h = 46.0

    def __init__(self, title, desc=''):
        super().__init__()
        self.title, self.desc = title, desc
        if desc:
            self.h = 58.0

    def draw(self, ui, cr, x, y, w):
        dl(cr, gfx.text_layout(self.title, 13, True), x + 4, y + 18, (*ui.accent, 1))
        if self.desc:
            dl(cr, gfx.make_layout(self.desc, 12, False, width=w, lines=1), x + 4, y + 38, (*ui.txt, .45))


class Switch(Row):
    def __init__(self, title, sub, get, set_, default=False):
        super().__init__()
        self.title, self.sub, self.get, self.set_, self.default = title, sub, get, set_, default
        self.h = 64.0 if sub else 54.0
        v = get()
        self.value = bool(self.default if v is None else v)
        self.spring('k', 1.0 if self.value else 0.0, omega=26, zeta=.6)

    def draw(self, ui, cr, x, y, w):
        self.title_block(ui, cr, x + PAD, y, self.title, self.sub, w - 120)
        k = clamp(self.sp['k'].x)
        self.sp['k'].t = 1.0 if self.value else 0.0
        tx_, ty = x + w - PAD - 46, y + self.h / 2 - 12
        hot = ui.zone(self, 'switch', x + w - PAD - 56, y, 56 + PAD, self.h)
        rrect(cr, tx_, ty, 46, 24, 12)
        cr.set_source_rgba(*[lerp(ui.txt[i] * .3, ui.accent[i], k) for i in range(3)], 1)
        cr.fill()
        cr.arc(tx_ + 12 + 22 * self.sp['k'].x, ty + 12, 9.2 + (.8 if hot else 0), 0, math.tau)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.fill()

    def click(self, ui, kind, lx, ly):
        old = self.value
        self.value = not old
        ui.apply(self.title, self.set_, self.value, lambda: old, self.set_back)

    def set_back(self, v):
        self.value = bool(v)


class Seg(Row):
    def __init__(self, title, sub, options, get, set_, default=None):
        super().__init__()
        self.title, self.sub, self.options, self.get, self.set_ = title, sub, options, get, set_
        self.values = [v for v, _ in options]
        cur = get()
        self.value = cur if cur in self.values else (default if default in self.values else self.values[0])
        self.spring('i', float(self.values.index(self.value)), omega=22, zeta=.75)
        self._lay = [gfx.text_layout(l, 13, True) for _, l in options]
        self.seg_w = [gfx.text_size(l)[0] + 28 for l in self._lay]
        self.below = sum(self.seg_w) > 330
        self.h = (100.0 if sub else 92.0) if self.below else (64.0 if sub else 54.0)

    def draw(self, ui, cr, x, y, w):
        self.title_block(ui, cr, x + PAD, y, self.title, self.sub, (w - 40) if self.below else (w - sum(self.seg_w) - 60))
        total = sum(self.seg_w)
        if self.below:
            sx, sy = x + PAD, y + self.h - 44
            total = min(total, w - 2 * PAD)
        else:
            sx, sy = x + w - PAD - total, y + (self.h - 32) / 2
        sh = 32.0
        rrect(cr, sx, sy, total, sh, 16)
        cr.set_source_rgba(*ui.txt, .08)
        cr.fill()
        i = self.values.index(self.value)
        self.sp['i'].t = float(i)
        # highlight: interpolate x/width between segment boundaries
        xs = [0.0]
        for wd in self.seg_w:
            xs.append(xs[-1] + wd)
        f = clamp(self.sp['i'].x, 0, len(self.values) - 1)
        i0 = int(math.floor(f))
        i1 = min(i0 + 1, len(self.values) - 1)
        t = f - i0
        hx = lerp(xs[i0], xs[i1], t)
        hw = lerp(self.seg_w[i0], self.seg_w[i1], t)
        rrect(cr, sx + hx + 2, sy + 2, hw - 4, sh - 4, 14)
        cr.set_source_rgba(*ui.accent, .9)
        cr.fill()
        for j, v in enumerate(self.values):
            hot = ui.zone(self, 'seg:%d' % j, sx + xs[j], sy, self.seg_w[j], sh)
            lab = self._lay[j]
            lw, lh = gfx.text_size(lab)
            dl(cr, lab, sx + xs[j] + (self.seg_w[j] - lw) / 2, sy + (sh - lh) / 2,
               (1, 1, 1, 1) if j == i else (*ui.txt, .85 if hot else .6))

    def click(self, ui, kind, lx, ly):
        j = int(kind.split(':')[1])
        new = self.values[j]
        if new != self.value:
            old = self.value
            self.value = new
            ui.apply(self.title, self.set_, new, lambda: old, self.set_back)

    def set_back(self, v):
        if v in self.values:
            self.value = v


class Step(Row):
    def __init__(self, title, sub, lo, hi, get, set_, default=0, step=1, suffix='', fmt=None):
        super().__init__()
        self.fmt = fmt
        self.title, self.sub, self.lo, self.hi, self.get, self.set_, self.step, self.suffix = title, sub, lo, hi, get, set_, step, suffix
        v = get()
        self.value = int(default if v is None else v)
        self.h = 64.0 if sub else 54.0
        self.spring('v', float(self.value), omega=24, zeta=.8)

    def draw(self, ui, cr, x, y, w):
        self.title_block(ui, cr, x + PAD, y, self.title, self.sub, w - 220)
        cy = y + self.h / 2
        self.sp['v'].t = float(self.value)
        for key, bx, sign in (('step:-', x + w - PAD - 140, -1), ('step:+', x + w - PAD - 14, 1)):
            hot = ui.zone(self, key, bx - 18, cy - 18, 36, 36)
            enabled = (sign < 0 and self.value > self.lo) or (sign > 0 and self.value < self.hi)
            s = ui.press_scale(self, key)
            cr.save()
            cr.translate(bx, cy)
            cr.scale(s, s)
            cr.arc(0, 0, 14, 0, math.tau)
            cr.set_source_rgba(*ui.txt, (.16 if hot else .08) if enabled else .04)
            cr.fill()
            cr.set_source_rgba(*ui.txt, .95 if enabled else .25)
            cr.set_line_width(1.8)
            cr.set_line_cap(1)
            cr.move_to(-4.5, 0)
            cr.line_to(4.5, 0)
            if sign > 0:
                cr.move_to(0, -4.5)
                cr.line_to(0, 4.5)
            cr.stroke()
            cr.restore()
        v = self.sp['v'].x
        label = self.fmt(round(v)) if self.fmt else '%d%s' % (round(v), self.suffix)
        lay = gfx.text_layout(label, 15, True)
        lw, lh = gfx.text_size(lay)
        dl(cr, lay, x + w - PAD - 77 - lw / 2, cy - lh / 2, (*ui.txt, 1))

    def click(self, ui, kind, lx, ly):
        d = self.step if kind.endswith('+') else -self.step
        new = max(self.lo, min(self.hi, self.value + d))
        if new != self.value:
            old = self.value
            self.value = new
            ui.press(self, kind)
            ui.apply(self.title, self.set_, new, lambda: old, self.set_back)

    def set_back(self, v):
        self.value = int(v)


class Button(Row):
    def __init__(self, title, sub, label, action):
        super().__init__()
        self.title, self.sub, self.label, self.action = title, sub, label, action
        self.h = 64.0 if sub else 54.0

    def draw(self, ui, cr, x, y, w):
        self.title_block(ui, cr, x + PAD, y, self.title, self.sub, w - 220)
        lay = gfx.text_layout(self.label, 13, True)
        lw, lh = gfx.text_size(lay)
        bw = lw + 32
        bx, by = x + w - PAD - bw, y + self.h / 2 - 16
        hot = ui.zone(self, 'btn', bx, by, bw, 32)
        s = ui.press_scale(self, 'btn')
        cr.save()
        cr.translate(bx + bw / 2, by + 16)
        cr.scale(s, s)
        rrect(cr, -bw / 2, -16, bw, 32, 16)
        cr.set_source_rgba(*ui.accent, .9 if hot else .75)
        cr.fill()
        cr.restore()
        dl(cr, lay, bx + 16, by + 16 - lh / 2, (1, 1, 1, 1))

    def click(self, ui, kind, lx, ly):
        ui.press(self, 'btn')
        self.action()


class Info(Row):
    def __init__(self, text, h=44.0):
        super().__init__()
        self.text, self.h = text, h

    def draw(self, ui, cr, x, y, w):
        t = self.text() if callable(self.text) else self.text
        dl(cr, gfx.make_layout(t, 13, False, width=w - 2 * PAD, lines=3), x + PAD, y + 12, (*ui.txt, .6))


class Cards(Row):
    """Image thumbnails in a grid (wallpapers). items: [(key, label, surface_getter)]."""

    def __init__(self, items, columns, on_pick, current, labels=False):
        super().__init__()
        self.labels = labels
        self.items, self.columns, self.on_pick, self.current = items, columns, on_pick, current
        self.cw, self.ch, self.gap = 0.0, 0.0, 12.0
        self.h = 100.0

    def layout(self, w):
        self.cw = (w - self.gap * (self.columns - 1)) / self.columns
        self.ch = self.cw * .6
        rows = max(1, math.ceil(len(self.items) / self.columns))
        self.h = rows * (self.ch + self.gap)

    def draw(self, ui, cr, x, y, w):
        self.layout(w)
        for i, (key, label, getter) in enumerate(self.items):
            r, c = divmod(i, self.columns)
            cx, cy = x + c * (self.cw + self.gap), y + r * (self.ch + self.gap)
            if cy + self.ch < ui.view_top or cy > ui.view_bottom:
                continue
            hot = ui.zone(self, 'card:%d' % i, cx, cy, self.cw, self.ch)
            cur = key == self.current()
            sp = self.spring('h%d' % i, 0.0, omega=22, zeta=.7)
            sp.t = 1.0 if hot else 0.0
            sc = 1 + .025 * sp.x
            cr.save()
            cr.translate(cx + self.cw / 2, cy + self.ch / 2)
            cr.scale(sc, sc)
            cr.translate(-self.cw / 2, -self.ch / 2)
            rrect(cr, 0, 0, self.cw, self.ch, 14)
            cr.save()
            cr.clip()
            surf = getter()
            if surf is not None:
                s = max(self.cw / surf.get_width(), self.ch / surf.get_height())
                cr.translate(self.cw / 2, self.ch / 2)
                cr.scale(s, s)
                cr.set_source_surface(surf, -surf.get_width() / 2, -surf.get_height() / 2)
                cr.paint()
            else:
                cr.set_source_rgba(*ui.txt, .08)
                cr.paint()
            if self.labels and label:
                g = cairo.LinearGradient(0, self.ch * .55, 0, self.ch)
                g.add_color_stop_rgba(0, 0, 0, 0, 0)
                g.add_color_stop_rgba(1, 0, 0, 0, .78)
                cr.set_source(g)
                cr.paint()
                dl(cr, gfx.make_layout(label, 12, True, width=self.cw - 20, lines=1), 10, self.ch - 24, (1, 1, 1, .95))
            cr.restore()
            if cur:
                rrect(cr, 1.5, 1.5, self.cw - 3, self.ch - 3, 13)
                cr.set_source_rgba(*ui.accent, 1)
                cr.set_line_width(3)
                cr.stroke()
            cr.restore()

    def click(self, ui, kind, lx, ly):
        i = int(kind.split(':')[1])
        self.on_pick(self.items[i][0])


class Group:
    """Rows drawn inside one rounded card, separated by hairlines."""

    def __init__(self, *rows, card=True):
        self.rows = list(rows)
        self.card = card

    @property
    def h(self):
        return sum(r.h for r in self.rows)


class Page:
    def __init__(self, title, *items):
        self.title = title
        self.items = list(items)       # Section | Group
        self.scroll = Spring(0, omega=18, zeta=.95)
        self.target = 0.0

    def height(self):
        h = 0.0
        for it in self.items:
            h += it.h + (14 if isinstance(it, Group) else 0)
        return h + 30

    def rows(self):
        for it in self.items:
            if isinstance(it, Group):
                yield from it.rows
            else:
                yield it


class Ui:
    """Holds the drawing state shared by rows: theme colours, zones, press feedback."""

    def __init__(self, apply_cb):
        self.txt = (.95, .95, .96)
        self.accent = (.21, .52, .89)
        self.zones = []
        self.pointer = None
        self.apply_cb = apply_cb
        self.pressed = {}
        self.view_top = 0.0
        self.view_bottom = 0.0

    def zone(self, row, kind, x, y, w, h):
        self.zones.append((row, kind, x, y, w, h))
        p = self.pointer
        return p is not None and x <= p[0] <= x + w and y <= p[1] <= y + h

    def apply(self, title, set_, value, old_get, set_back):
        self.apply_cb(title, set_, value, old_get, set_back)

    def press(self, row, key):
        sp = row.spring('p:' + key, 0.0, omega=26, zeta=.35)
        sp.x, sp.v, sp.t = -.15, 0.0, 0.0

    def press_scale(self, row, key):
        sp = row.sp.get('p:' + key)
        return 1.0 + (sp.x if sp else 0.0)

    def draw_page(self, cr, page, x, y, w, view_h):
        """Draw a page's groups; returns nothing. Coordinates: (x, y) top-left of the content area, y already scrolled."""
        yy = y
        for it in page.items:
            if isinstance(it, Section):
                it.draw(self, cr, x, yy, w)
                yy += it.h
                continue
            gh = it.h
            if it.card:
                rrect(cr, x, yy, w, gh, 18)
                cr.set_source_rgba(*self.txt, .055)
                cr.fill()
            ry = yy
            for i, r in enumerate(it.rows):
                if ry + r.h >= -20 and ry <= view_h + 20:
                    hot = self.pointer is not None and x <= self.pointer[0] <= x + w and ry <= self.pointer[1] <= ry + r.h
                    if hot and r.kind == 'row' and not isinstance(r, (Cards,)):
                        rrect(cr, x + 4, ry + 3, w - 8, r.h - 6, 14)
                        cr.set_source_rgba(*self.txt, .045)
                        cr.fill()
                    r.draw(self, cr, x, ry, w)
                if i < len(it.rows) - 1 and it.card:
                    cr.set_source_rgba(*self.txt, .07)
                    cr.set_line_width(1)
                    cr.move_to(x + PAD, round(ry + r.h) + .5)
                    cr.line_to(x + w - PAD, round(ry + r.h) + .5)
                    cr.stroke()
                ry += r.h
            yy += gh + 14
        return yy

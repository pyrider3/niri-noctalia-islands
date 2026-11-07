"""Barrel theme: the tape is a glass cylinder turning towards you, like a rotary dial."""
import math, cairo
from theme_tape import TapeTheme
from theme_kit import WHITE, GRAY, ORANGE, mix, smooth, capsule, fill_capsule, glow, soft_glow, label, text_width

STEP = .52                           # angle between neighbouring windows (rad)

class BarrelTheme(TapeTheme):
    ROW_TAPE = 27.
    def radius(self, width): return width*.37
    def project(self, o, width, step=STEP):
        th = max(-1.45, min(1.45, o*step))
        return width/2+self.radius(width)*math.sin(th), math.cos(th)

    def point(self, index, width, now, windows=False):
        lin = super().point(index, width, now, windows)
        if windows and index in self.floating_indices: return lin
        sp = self.window_spacing(width, now) if windows else self.workspace_spacing.at(now)
        return self.project((lin-width/2)/max(sp, 1.), width, STEP if windows else STEP*.8)[0]

    def draw_dot(self, c, x, y, near, lift, a, accent, urgent, scale):
        o = (x-self.ruler_w/2)/max(self._ws_sp, 1.)
        x, s = self.project(o, self.ruler_w, STEP*.8)
        a *= s**1.3*smooth((1.45-abs(o)*STEP*.8)/.35)
        rgb = ORANGE if urgent else mix(WHITE, accent, .8*near)
        if near > .05: glow(c, x, y, 9, rgb, .38*near*a)
        w = (3.4+5.5*near)*scale*s; h = (3.2+1.4*near)*scale
        fill_capsule(c, x, y, w, h, rgb, a*(.55+.45*near+.2*lift))

    def paint(self, ruler, now):
        self.ruler_w = ruler.width
        return super().paint(ruler, now)

    def states(self, ruler, now, position, spacing, reveal=1.):
        out = super().states(ruler, now, position, spacing, reveal)
        for st in out:
            st['x'], st['s'] = self.project(st['o'], ruler.width)
            th = abs(st['o'])*STEP
            st['a'] = reveal*st['s']**1.2*smooth((1.45-th)/.35)
        return out

    def draw_tape(self, c, ruler, now, accent, sts, position, spacing):
        width = ruler.width; center = width/2; cy = self.ROW_TAPE
        # cylinder body: a soft vertical sheen in the middle, vignette towards the turning edges
        sheen = cairo.LinearGradient(0, 0, width, 0)
        for stop, al in ((0, 0), (.28, .015), (.5, .075), (.72, .015), (1, 0)): sheen.add_color_stop_rgba(stop, 1, 1, 1, al)
        c.save(); capsule(c, center, cy, width*.92, 26); c.clip()
        c.set_source(sheen); c.paint()
        glow(c, center, cy+11, width*.22, accent, .13)
        c.restore()
        # horizontal rails with perspective (hairlines fade where the cylinder turns away)
        for dy, al in ((-13.5, .16), (13.5, .13)):
            g = cairo.LinearGradient(0, 0, width, 0)
            for stop, k in ((0, 0), (.2, 1), (.8, 1), (1, 0)): g.add_color_stop_rgba(stop, *mix(WHITE, accent, .3), al*k)
            c.set_source(g); c.set_line_width(.7); c.move_to(width*.04, cy+dy); c.line_to(width*.96, cy+dy); c.stroke()
        for st in sorted(sts, key=lambda s: s['m']):
            s = st['s']; m = st['m']; a = st['a']; x = st['x']
            labw = text_width(c, st['label'], 7.2)+12
            w = (8+(labw-8)*m)*(.2+.8*s)
            h = (9+7*m+1.5*st['lift'])*(.55+.45*s)
            rgb = ORANGE if st['urgent'] else mix(GRAY, accent, m)
            if m > .08: soft_glow(c, x, cy, w, h, cy, 42-cy, rgb, .5*m*a)
            capsule(c, x, cy, w, h)
            body = cairo.LinearGradient(0, cy-h/2, 0, cy+h/2)
            body.add_color_stop_rgba(0, *mix(rgb, WHITE, .42), a*(.38+.57*m)); body.add_color_stop_rgba(1, *rgb, a*(.24+.7*m))
            c.set_source(body); c.fill_preserve()
            c.set_source_rgba(*mix(rgb, WHITE, .7), a*(.18+.3*m)); c.set_line_width(.6); c.stroke()      # glass rim
            if m > .55:
                label(c, st['label'], x, cy+2.5, 7.2, (.04, .06, .1), (m-.55)/.45*a)

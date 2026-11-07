"""Pearls theme: windows are pearls on a string; the focused pearl is heavy and sinks into a gravity well."""
import math, cairo
from theme_tape import TapeTheme
from theme_kit import WHITE, GRAY, ORANGE, mix, smooth, glow, soft_glow, label

PEARL = (.93, .94, 1.)

def pearl(c, x, y, r, rgb, a):
    g = cairo.RadialGradient(x-.34*r, y-.42*r, .06*r, x, y, r)
    g.add_color_stop_rgba(0, 1, 1, 1, a)
    g.add_color_stop_rgba(.38, *mix(rgb, WHITE, .35), a)
    g.add_color_stop_rgba(.8, *rgb, a)
    g.add_color_stop_rgba(1, *mix(rgb, (0, 0, 0), .5), a)
    c.set_source(g); c.arc(x, y, r, 0, math.tau); c.fill()
    c.set_source_rgba(1, 1, 1, a*.9); c.arc(x-.36*r, y-.44*r, max(.35, .17*r), 0, math.tau); c.fill()   # specular

class PearlsTheme(TapeTheme):
    ROW_TAPE = 23.
    WELL = 4.5          # how far the focused pearl drags the string down
    def string_y(self, x, width, spacing):
        dx = x-width/2
        return self.ROW_TAPE+1-9*min(1., (dx/(width*.5))**2)+self.WELL*math.exp(-(dx/(spacing*1.15+4))**2)

    def draw_dot(self, c, x, y, near, lift, a, accent, urgent, scale):
        rgb = ORANGE if urgent else mix(PEARL, accent, .85*near)
        if near > .05: glow(c, x, y, 9, rgb, .4*near*a)
        pearl(c, x, y, (1.5+1.7*near+.5*lift)*scale, rgb, a*(.7+.3*near))

    def draw_tape(self, c, ruler, now, accent, sts, position, spacing):
        width = ruler.width; center = width/2
        # the string
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        n = 70; prev = None
        for k in range(n+1):
            x = width*(.04+.92*k/n); y = self.string_y(x, width, spacing)
            if prev:
                a = self.fade(x, width)*.55
                if a > .01:
                    c.set_source_rgba(*mix(GRAY, accent, math.exp(-((x-center)/30)**2)*.8), a)
                    c.set_line_width(.8); c.move_to(*prev); c.line_to(x, y); c.stroke()
            prev = (x, y)
        sp = self.speed(now, spacing)
        for s in sorted(sts, key=lambda s: s['m']):               # focused pearl drawn last
            m = s['m']; a = s['a']; x = s['x']
            # pearls lag behind a fast-moving string, like beads swinging on a thread
            sway = max(-3.5, min(3.5, sp*.009))*(.3+m)
            y = self.string_y(x, width, spacing)
            r = 2.3+4.0*m+1.1*s['lift']
            rgb = ORANGE if s['urgent'] else mix(PEARL, accent, .82*m)
            if m > .05: soft_glow(c, x+sway, y, r*2, r*2, y, 42-y, rgb, .55*m*a)
            c.set_source_rgba(0, 0, 0, a*.25); c.arc(x+sway, y+r*.3+.6, r*1.02, 0, math.tau); c.fill()
            pearl(c, x+sway, y, r, rgb, a*(.62+.38*m))
            if m > .5:
                label(c, s['label'], x+sway, 40.8, 6.2, mix(WHITE, accent, .5), a*(m-.5)*2*.9)

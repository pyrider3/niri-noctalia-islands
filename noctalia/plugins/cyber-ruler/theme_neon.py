"""Neon theme: glass tubes that are dark until focused, then ignite with a short flicker."""
import math, cairo
from theme_tape import TapeTheme
from theme_kit import WHITE, GRAY, ORANGE, mix, smooth, soft_glow, glow, label

FLICKER = ((0., .06, 1.), (.06, .11, .12), (.11, .19, .95), (.19, .25, .18), (.25, .31, .9), (.31, .35, .4))   # (from, to, level)

def ignition(t):
    if t < 0: return 1.
    for lo, hi, level in FLICKER:
        if lo <= t < hi: return level
    return 1.

def tube(c, x1, y1, x2, y2, rgb, power, a, core_w=1.5):
    """Neon tube: stacked halos, saturated body, hot white core."""
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    for w, k in ((11, .05), (7.5, .09), (4.6, .2), (core_w+1.3, .85)):
        c.set_source_rgba(*rgb, a*power*k); c.set_line_width(w); c.move_to(x1, y1); c.line_to(x2, y2); c.stroke()
    c.set_source_rgba(*mix(rgb, WHITE, .82), a*power); c.set_line_width(core_w*.6); c.move_to(x1, y1); c.line_to(x2, y2); c.stroke()

class NeonTheme(TapeTheme):
    ROW_TAPE = 22.5
    def __init__(self):
        super().__init__(); self._active = None; self._ignite = -10.
    def moving(self, now):
        return super().moving(now) or 0 <= now-self._ignite < .4

    def draw_dot(self, c, x, y, near, lift, a, accent, urgent, scale):
        rgb = ORANGE if urgent else mix(GRAY, accent, near)
        r = (2.0+.9*near)*scale
        if near > .05: soft_glow(c, x, y, r*2, r*2, y, 20, rgb, .6*near*a)
        c.set_source_rgba(*rgb, a*(.32+.68*near+.2*lift)); c.set_line_width(.9+.5*near)
        c.arc(x, y, r, 0, math.tau); c.stroke()
        if near > .3:
            c.set_source_rgba(*mix(rgb, WHITE, .8), a*near); c.arc(x, y, r*.3, 0, math.tau); c.fill()

    def draw_tape(self, c, ruler, now, accent, sts, position, spacing):
        width = ruler.width; center = width/2; cy = self.ROW_TAPE
        axis = ruler.window_axis
        if axis.active != self._active:
            self._ignite = now if self._active is not None and ruler.animate else -10.; self._active = axis.active
        power = ignition(now-self._ignite)
        for s in sts:
            m = s['m']; a = s['a']; x = s['x']
            h = 4+4.5*m+1.5*s['lift']
            lit = m*power
            rgb = ORANGE if s['urgent'] else mix(mix(GRAY, accent, .15), accent, m)
            # off tube: a dark glass rod with a faint reflection
            c.set_source_rgba(*GRAY, a*(.22+.1*s['lift'])*(1-.6*m)); c.set_line_width(2.2); c.set_line_cap(cairo.LINE_CAP_ROUND)
            c.move_to(x, cy-h); c.line_to(x, cy+h); c.stroke()
            c.set_source_rgba(1, 1, 1, a*.12*(1-m)); c.set_line_width(.5); c.move_to(x-.5, cy-h+1); c.line_to(x-.5, cy+h-1); c.stroke()
            if lit > .02:
                soft_glow(c, x, cy, 6, h*2, cy, 42-cy, rgb, .55*lit*a)
                tube(c, x, cy-h, x, cy+h, rgb, lit, a, 1.6+.6*m)
        focus = max(sts, key=lambda s: s['m'], default=None)
        if focus and focus['m'] > .5 and power > .5:
            label(c, focus['label'], focus['x'], 39.8, 6.2, mix(WHITE, accent, .6), focus['a']*(focus['m']-.5)*2*power*.9)

"""Stars theme: windows are stars of a constellation drifting over a parallax star field."""
import math, cairo
from theme_tape import TapeTheme
from theme_kit import WHITE, GRAY, ORANGE, mix, smooth, glow, label

def h01(n, salt=0):
    x = (int(n)*374761393 + salt*668265263 + 144665) & 0xffffffff
    x = ((x ^ (x >> 13))*1274126177) & 0xffffffff
    x ^= x >> 16
    return x/0xffffffff

def sparkle(c, x, y, r, rgb, a, thin=.13):
    """Four-point star flare."""
    t = r*thin
    c.new_path(); c.move_to(x, y-r); c.line_to(x+t, y-t); c.line_to(x+r, y); c.line_to(x+t, y+t)
    c.line_to(x, y+r); c.line_to(x-t, y+t); c.line_to(x-r, y); c.line_to(x-t, y-t); c.close_path()
    c.set_source_rgba(*rgb, max(0., min(1., a))); c.fill()

DUST = [(h01(i, 1), 3+h01(i, 2)*36, .3+h01(i, 3)*.5, .25+h01(i, 4)*.55, .12+h01(i, 5)*.3) for i in range(90)]

class StarsTheme(TapeTheme):
    ROW_TAPE = 26.
    def draw_dot(self, c, x, y, near, lift, a, accent, urgent, scale):
        rgb = ORANGE if urgent else mix(WHITE, accent, .75*near)
        if near > .05: glow(c, x, y, 8, rgb, .35*near*a)
        c.set_source_rgba(*rgb, a*(.5+.5*near)); c.arc(x, y, (1.15+.9*near+.4*lift)*scale, 0, math.tau); c.fill()
        if near > .12: sparkle(c, x, y, 2.4+3.6*near, rgb, a*near*.95)

    def draw_tape(self, c, ruler, now, accent, sts, position, spacing):
        width = ruler.width; center = width/2; cy = self.ROW_TAPE
        # parallax dust: three depth layers drifting at 18 / 32 / 46 % of the tape
        span = width+60.
        for u, y, r, al, depth in DUST:
            layer = .18+.28*depth/.42
            x = (u*span-(position*spacing)*layer) % span-30
            a = self.fade(x, width)*al*(.55+.45*math.sin(u*40+position*3.1))
            if a > .01:
                c.set_source_rgba(*mix(WHITE, accent, .25), a); c.arc(x, y, r*(.7+.5*depth/.42), 0, math.tau); c.fill()
        if not sts: return
        pts = []
        for s in sts:
            y = cy+(h01(s['wid'], 7)-.5)*11*(1-.55*s['m'])
            pts.append((s['x'], y))
        # constellation lines
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        for k in range(len(sts)-1):
            a = min(sts[k]['a'], sts[k+1]['a'])*(.22+.35*max(sts[k]['m'], sts[k+1]['m']))
            if a < .01: continue
            c.set_source_rgba(*mix(GRAY, accent, max(sts[k]['m'], sts[k+1]['m'])), a)
            c.set_line_width(.6+.5*max(sts[k]['m'], sts[k+1]['m']))
            c.move_to(*pts[k]); c.line_to(*pts[k+1]); c.stroke()
        for s, (x, y) in zip(sts, pts):
            m = s['m']; a = s['a']; lift = s['lift']
            rgb = ORANGE if s['urgent'] else mix(mix(WHITE, GRAY, .25), accent, m)
            r = 1.2+1.1*h01(s['wid'], 9)+2.1*m+1.0*lift
            glow(c, x, y, 5+11*m+4*lift, rgb, (.18+.42*m+.2*lift)*a)
            c.set_source_rgba(*mix(rgb, WHITE, .55), a*(.62+.38*m)); c.arc(x, y, r, 0, math.tau); c.fill()
            if m > .08 or lift > .3:
                k = max(m, lift*.6)
                sparkle(c, x, y, 3+8*k, mix(rgb, WHITE, .5), a*k*.95)
                sparkle(c, x, y, 2.5+4*k, mix(rgb, WHITE, .8), a*k*.6, .5)
            if m > .5:
                label(c, s['label'], x, 39.5, 6.5, mix(WHITE, accent, .55), a*(m-.5)*2*.9)

"""Mercury theme: windows are liquid-metal droplets. The focused one is a big drop that stretches
into a goo tail when the tape moves and bonds with neighbours (metaball field via PIL)."""
import math, cairo
from PIL import Image, ImageDraw, ImageFilter, ImageChops
from theme_tape import TapeTheme
from theme_kit import WHITE, GRAY, ORANGE, mix, smooth, glow, soft_glow, label

SILVER = (.80, .83, .92)
Q = 2        # field resolution = canvas pixel scale

def ramp(lo, hi):
    lut = [0]*256
    for v in range(256):
        t = (v-lo)/max(1, hi-lo); lut[v] = int(255*max(0., min(1., t))**1.0)
    return lut

THRESH = ramp(80, 108)          # sharp-but-antialiased metaball surface
SOFT = ramp(70, 160)

class MercuryTheme(TapeTheme):
    ROW_TAPE = 26.
    def draw_dot(self, c, x, y, near, lift, a, accent, urgent, scale):
        rgb = ORANGE if urgent else mix(SILVER, accent, .85*near)
        r = (1.5+1.8*near+.5*lift)*scale
        if near > .05: soft_glow(c, x, y, r*2, r*2, y, 20, rgb, .45*near*a)
        g = cairo.RadialGradient(x-.3*r, y-.4*r, .05*r, x, y, r)
        g.add_color_stop_rgba(0, 1, 1, 1, a); g.add_color_stop_rgba(.45, *rgb, a); g.add_color_stop_rgba(1, *mix(rgb, (0, 0, .1), .55), a)
        c.set_source(g); c.arc(x, y, r, 0, math.tau); c.fill()

    def draw_tape(self, c, ruler, now, accent, sts, position, spacing):
        if not sts: return
        width, height = ruler.width, ruler.height; cy = self.ROW_TAPE
        W, H = width*Q, height*Q
        field = Image.new('L', (W, H), 0); sel = Image.new('L', (W, H), 0)
        hi = Image.new('L', (W, H), 0)
        fd, sd, hd = ImageDraw.Draw(field), ImageDraw.Draw(sel), ImageDraw.Draw(hi)
        speed = self.speed(now, spacing)
        def blob(d, x, y, rx, ry, v=255):
            d.ellipse([ (x-rx)*Q, (y-ry)*Q, (x+rx)*Q, (y+ry)*Q ], fill=v)
        focus = max(sts, key=lambda s: s['m'])
        for s in sts:
            m = s['m']; x = s['x']; a = s['a']
            if a < .02: continue
            r = (2.6+4.6*m+1.1*s['lift'])*(.55+.45*min(1., a*1.6))
            y = cy
            blob(fd, x, y, r, r)
            if m > .02: blob(sd, x, y, r, r, int(255*min(1., m*1.15)))
            blob(hd, x-.3*r, y-.38*r, max(.5, r*.34), max(.45, r*.26), int(255*min(1., .25+m)))
            if m > .12:
                # goo tail: a chain of shrinking drops trailing against the direction of travel
                direction = 1. if speed > 0 else -1.
                tail = min(30., abs(speed)*.07)*m
                for t in range(1, 7):
                    f = t/6; rr = r*(1-.72*f)
                    if tail*f > .5: blob(fd, x+direction*tail*f, y, rr, rr*(1-.1*f)); blob(sd, x+direction*tail*f, y, rr, rr, int(255*m*(1-.5*f)))
        # a gooey bridge between neighbouring drops while the focus travels between them
        for left, right in zip(sts, sts[1:]):
            k = min(left['m'], right['m'])
            if k > .12:
                rl = 2.6+4.6*left['m']; rr = 2.6+4.6*right['m']
                bx = (left['x']+right['x'])/2; br = min(rl, rr)*.95*smooth(k*2.2)
                blob(fd, bx, cy, br, br*.8); blob(sd, bx, cy, br, br*.8, int(255*k))
        blur = 5.4*Q/2
        F = field.filter(ImageFilter.GaussianBlur(blur)).point(THRESH)
        S = sel.filter(ImageFilter.GaussianBlur(blur*1.2)).point(SOFT)
        S = ImageChops.darker(S, F)
        # rim light: the surface minus itself shifted down-left -> bright upper-right edge, dark lower-left
        shifted = ImageChops.offset(F, -Q, Q)
        rim = ImageChops.subtract(F, shifted).point(lambda v: min(255, v*3))
        shade = ImageChops.offset(F, Q, -Q); shade = ImageChops.subtract(F, shade).point(lambda v: min(255, v*2))
        H_ = hi.filter(ImageFilter.GaussianBlur(1.1*Q/2))
        H_ = ImageChops.darker(H_, F)
        def solid(rgb): return Image.new('RGB', (W, H), tuple(int(255*v) for v in rgb))
        top = Image.linear_gradient('L').resize((W, H))               # 0 at top -> 255 at bottom
        body = Image.composite(solid(mix(SILVER, (.18, .2, .32), .55)), solid(mix(SILVER, WHITE, .35)), top)
        tint = Image.composite(solid(mix(accent, (0, 0, .08), .22)), solid(mix(accent, WHITE, .5)), top)
        img = Image.composite(tint, body, S)
        img = Image.composite(solid((1, 1, 1)), img, rim.point(lambda v: v//2))
        img = Image.composite(solid((0, 0, .06)), img, shade.point(lambda v: v//3))
        img = Image.composite(solid((1, 1, 1)), img, H_)
        alpha = F.point(lambda v: int(v*.96))
        rgba = img.convert('RGBA'); rgba.putalpha(alpha)
        data = bytearray(rgba.convert('RGBa').tobytes('raw', 'BGRa'))
        surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, W, H, W*4)
        # soft accent bloom under the focused drop, then the metal itself
        soft_glow(c, focus['x'], cy, 12, 12, cy, height-cy, accent, .5*focus['m']*focus['a'])
        c.save(); c.scale(1/Q, 1/Q); c.set_source_surface(surf, 0, 0)
        # edge fade: fade the whole layer with the tape's cosine fade by painting through a mask
        mask = cairo.LinearGradient(0, 0, W, 0)
        for stop, k in ((0, 0), (.12, 1), (.88, 1), (1, 0)): mask.add_color_stop_rgba(stop, 0, 0, 0, k)
        c.mask(mask); c.restore()
        if focus['m'] > .5:
            label(c, focus['label'], focus['x'], 40.5, 6.2, mix(WHITE, accent, .55), focus['a']*(focus['m']-.5)*2*.9)

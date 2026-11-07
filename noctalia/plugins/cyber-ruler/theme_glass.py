"""Glass theme: the aviation tape on a frosted, edge-faded glass rail with an accent under-glow."""
import cairo
from heading_spring import HeadingTheme as SpringHeadingTheme
from theme_kit import DEFAULT, capsule, glow

class GlassTheme(SpringHeadingTheme):
    def accent_color(self, ruler):
        return ruler.accent_rgb(DEFAULT)

    def backdrop(self, c, ruler, now):
        w, h = ruler.width, ruler.height
        accent = self.accent_color(ruler)
        x0, x1, y0, y1 = w*.04, w*.96, 2., h-2.
        c.push_group()
        capsule(c, w/2, (y0+y1)/2, x1-x0, y1-y0)
        c.save(); c.clip_preserve()
        body = cairo.LinearGradient(0, y0, 0, y1)
        body.add_color_stop_rgba(0, 1, 1, 1, .15); body.add_color_stop_rgba(.5, 1, 1, 1, .06); body.add_color_stop_rgba(1, 1, 1, 1, .035)
        c.set_source(body); c.fill_preserve()
        glow(c, w/2, y1, w*.2, accent, .34)           # light cast onto the glass by the active tick
        c.restore()
        capsule(c, w/2, (y0+y1)/2, x1-x0, y1-y0)
        rim = cairo.LinearGradient(0, y0, 0, y1)
        rim.add_color_stop_rgba(0, 1, 1, 1, .34); rim.add_color_stop_rgba(.45, 1, 1, 1, .08); rim.add_color_stop_rgba(1, 1, 1, 1, .16)
        c.set_source(rim); c.set_line_width(.9); c.stroke()
        c.pop_group_to_source()
        fade = cairo.LinearGradient(x0, 0, x1, 0)
        for stop, a in ((0, 0), (.16, 1), (.84, 1), (1, 0)): fade.add_color_stop_rgba(stop, 0, 0, 0, a)
        c.mask(fade)

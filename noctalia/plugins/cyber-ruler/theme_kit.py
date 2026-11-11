"""Small Cairo helpers shared by the glass / pill / merged themes."""
import math, cairo

DEFAULT = (.53, .77, .98)
WHITE = (.96, .975, 1.)
GRAY = (.79, .80, .91)
ORANGE = (1., .55, .36)

def mix(a, b, t):
    return tuple(x+(y-x)*t for x, y in zip(a, b))

def smooth(t):
    t = max(0., min(1., t))
    return t*t*(3-2*t)

def capsule(c, x, y, w, h):
    """Path of a fully rounded capsule centred on (x, y)."""
    w = max(w, h); r = h/2
    c.new_sub_path()
    c.arc(x+w/2-r, y, r, -math.pi/2, math.pi/2)
    c.arc(x-w/2+r, y, r, math.pi/2, 3*math.pi/2)
    c.close_path()

def fill_capsule(c, x, y, w, h, rgb, a=1.):
    capsule(c, x, y, w, h); c.set_source_rgba(*rgb, max(0., min(1., a))); c.fill()

def glow(c, x, y, radius, rgb, a):
    g = cairo.RadialGradient(x, y, 0, x, y, radius)
    g.add_color_stop_rgba(0, *rgb, a); g.add_color_stop_rgba(1, *rgb, 0)
    c.set_source(g); c.arc(x, y, radius, 0, math.tau); c.fill()

def label(c, value, x, y, size, rgb, a=1.):
    c.select_font_face('DejaVu Sans Mono', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    c.set_font_size(size); ext = c.text_extents(value)
    c.set_source_rgba(*rgb, max(0., min(1., a)))
    c.move_to(x-ext.width/2-ext.x_bearing, y); c.show_text(value)

def text_width(c, value, size):
    c.select_font_face('DejaVu Sans Mono', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    c.set_font_size(size); return c.text_extents(value).x_advance

def soft_glow(c, x, y, w, h, room_up, room_down, rgb, a):
    """Elliptical halo around a capsule of size w x h. Wide, with a long quadratic-ish tail that
    reaches 0 before the canvas edge, so it never gets cut off."""
    rx = w/2+26
    ry = max(4., min(h/2+13, room_up-1.5, room_down-1.5))
    c.save(); c.translate(x, y); c.scale(1, ry/rx)
    g = cairo.RadialGradient(0, 0, 0, 0, 0, rx)
    for stop, k in ((0, 1), (.3, .62), (.55, .3), (.78, .1), (1, 0)): g.add_color_stop_rgba(stop, *rgb, a*k)
    c.set_source(g); c.arc(0, 0, rx, 0, math.tau); c.fill(); c.restore()


# ---- liquid glass (same switch as the islands: ~/.local/state/desk-style/style.json)
import json as _json, os as _os, time as _time
_STYLE = {'t': 0.0, 'v': False}


def glass_on():
    now = _time.monotonic()
    if now - _STYLE['t'] > 1.0:
        _STYLE['t'] = now
        try:
            _STYLE['v'] = _json.load(open(_os.path.expanduser('~/.local/state/desk-style/style.json'))).get('style') == 'glass'
        except (OSError, ValueError):
            _STYLE['v'] = False
    return _STYLE['v']


def glass_fill(c, alpha=1.0, tint=.40):
    """Fill + rim the current path as translucent glass (no backdrop snapshot here: the bar shows through)."""
    x1, y1, x2, y2 = c.path_extents()
    w, h = max(1., x2 - x1), max(1., y2 - y1)
    c.save(); c.clip_preserve()
    c.set_source_rgba(.045, .055, .09, tint * alpha); c.paint()
    g = cairo.LinearGradient(0, y1, 0, y2)
    g.add_color_stop_rgba(0, 1, 1, 1, .20 * alpha); g.add_color_stop_rgba(.5, 1, 1, 1, .05 * alpha); g.add_color_stop_rgba(1, 1, 1, 1, .09 * alpha)
    c.set_source(g); c.paint()
    b = cairo.RadialGradient(x1 + w * .2, y1 + h * .1, 0, x1 + w * .2, y1 + h * .1, max(w, h) * .6)
    b.add_color_stop_rgba(0, 1, 1, 1, .22 * alpha); b.add_color_stop_rgba(1, 1, 1, 1, 0)
    c.set_source(b); c.paint()
    c.restore()
    r = cairo.LinearGradient(x1, y1, x2, y2)
    r.add_color_stop_rgba(0, 1, 1, 1, .75 * alpha); r.add_color_stop_rgba(.4, 1, 1, 1, .18 * alpha)
    r.add_color_stop_rgba(.7, 1, 1, 1, .12 * alpha); r.add_color_stop_rgba(1, 1, 1, 1, .38 * alpha)
    c.set_source(r); c.set_line_width(.8); c.stroke_preserve()
    c.set_source_rgba(0, 0, 0, .22 * alpha); c.set_line_width(.35); c.stroke()

"""Shared drawing helpers for the notification toasts and centre."""
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

import cairo
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

TAU = 2 * math.pi
FONT = 'Noto Sans CJK SC'
THEME_FILE = Path.home() / '.local/state/status-capsule/input.json'


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def mix(a, b, t):
    return tuple(lerp(a[i], b[i], t) for i in range(3))


def hex_rgb(value, fallback):
    try:
        return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (TypeError, ValueError, IndexError):
        return fallback


# ------------------------------------------------------------------ theme
class Theme:
    """Colours follow the Noctalia theme (published by the status-capsule widget)."""

    def __init__(self):
        self.accent = (.21, .52, .89)
        self.text = (.95, .95, .95)
        self.bg = (.04, .04, .05)
        self.danger = (1.0, .36, .38)
        self._read = 0.0
        self.refresh(force=True)

    def refresh(self, force=False):
        now = time.monotonic()
        if not force and now - self._read < 2.0:
            return
        self._read = now
        try:
            d = json.loads(THEME_FILE.read_text())
        except (OSError, ValueError):
            return
        self.accent = hex_rgb(d.get('accent'), self.accent)
        self.text = hex_rgb(d.get('text'), self.text)
        self.bg = hex_rgb(d.get('bg'), self.bg)

    @property
    def card(self):
        return mix(self.bg, self.text, .075)

    @property
    def card_hi(self):
        return mix(self.bg, self.text, .13)


THEME = Theme()


# ----------------------------------------------------------------- spring
class Spring:
    """Under-damped spring; zeta < 1 gives the overshoot that makes motion feel alive."""

    def __init__(self, x=0.0, omega=26.0, zeta=.62):
        self.x = self.t = float(x)
        self.v = 0.0
        self.o, self.z = omega, zeta

    def step(self, dt):
        dt = min(.05, max(0.0, dt))
        n = int(dt / .004) + 1
        h = dt / n
        for _ in range(n):
            self.v += (-2 * self.z * self.o * self.v - self.o * self.o * (self.x - self.t)) * h
            self.x += self.v * h
        if abs(self.x - self.t) < .01 and abs(self.v) < .02:
            self.x, self.v = self.t, 0.0

    def snap(self, value):
        self.x = self.t = float(value)
        self.v = 0.0

    @property
    def settled(self):
        return self.x == self.t and self.v == 0.0


# ----------------------------------------------------------------- shapes
def rrect(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


_shadow_cache = {}


def shadow(cr, x, y, w, h, r, strength=1.0, dy=6):
    """Soft shadow, rendered once per size and then just painted."""
    strength = round(strength * 2) / 2
    key = (int(w), int(h), int(r), strength, dy)
    surf = _shadow_cache.get(key)
    m = 28
    if surf is None:
        if len(_shadow_cache) > 40:
            _shadow_cache.clear()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int((w + 2 * m) * 2), int((h + 2 * m) * 2))
        surf.set_device_scale(2, 2)
        c = cairo.Context(surf)
        for i in range(7):
            gp = 1 + i * 2.2
            rrect(c, m - gp, m - gp + dy, w + 2 * gp, h + 2 * gp, r + gp)
            c.set_source_rgba(0, 0, 0, .05 * strength * (1 - i / 8))
            c.fill()
        _shadow_cache[key] = surf
    cr.set_source_surface(surf, x - m, y - m)
    cr.paint()


# ------------------------------------------------------------------- text
_scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


_FONT_OPTS = cairo.FontOptions()
_FONT_OPTS.set_hint_style(cairo.HINT_STYLE_NONE)
_FONT_OPTS.set_hint_metrics(cairo.HINT_METRICS_OFF)   # glyph advances must not change with the scale/rotation
_FONT_OPTS.set_antialias(cairo.ANTIALIAS_GRAY)


def make_layout(text, size, bold=False, width=None, lines=None, markup=False, cr=None):
    lay = PangoCairo.create_layout(cr or _scratch)
    PangoCairo.context_set_font_options(lay.get_context(), _FONT_OPTS)
    desc = Pango.FontDescription.from_string(f'{FONT} {"Bold " if bold else ""}{size}px')
    lay.set_font_description(desc)
    if width is not None:
        lay.set_width(int(width * Pango.SCALE))
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
    if lines:
        lay.set_height(-lines)
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    if markup:
        try:
            Pango.parse_markup(text, -1, '\0')
            lay.set_markup(text, -1)
        except GLib.Error:
            lay.set_text(strip_markup(text), -1)
    else:
        lay.set_text(text, -1)
    return lay


_small = {}


def text_layout(text, size, bold=False):
    """Cached layout for short, unconstrained strings drawn every frame."""
    key = (text, size, bold)
    lay = _small.get(key)
    if lay is None:
        if len(_small) > 400:
            _small.clear()
        lay = make_layout(text, size, bold)
        _small[key] = lay
    return lay


def draw_layout(cr, lay, x, y, rgba):
    cr.set_source_rgba(*rgba)
    cr.move_to(x, y)
    PangoCairo.update_layout(cr, lay)
    PangoCairo.show_layout(cr, lay)


def text_size(lay):
    return lay.get_pixel_size()


_TAG = re.compile(r'</?(?!b>|i>|u>|/b>|/i>|/u>)[^>]*>')


def strip_markup(s):
    return re.sub(r'<[^>]*>', '', s or '').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')


def safe_markup(body):
    """Keep <b>/<i>/<u>, drop every other tag, escape stray ampersands."""
    s = body or ''
    s = _TAG.sub('', s)
    s = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;)', '&amp;', s)
    return s


def ago(ts):
    d = max(0, int(time.time() - ts))
    if d < 45:
        return '刚刚'
    if d < 3600:
        return f'{d // 60 or 1} 分钟前'
    if d < 86400:
        return f'{d // 3600} 小时前'
    return time.strftime('%m-%d %H:%M', time.localtime(ts))


# ------------------------------------------------------------------ icons
_icon_cache = {}


def _surface_from_pixbuf(pb):
    """GdkPixbuf (straight RGB/RGBA) -> cairo ARGB32 surface (premultiplied BGRA). GTK4 has no helper for this."""
    w, h = pb.get_width(), pb.get_height()
    n = pb.get_n_channels()
    stride = pb.get_rowstride()
    src = pb.get_pixels()
    has_alpha = pb.get_has_alpha()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    dst = surf.get_data()
    dstride = surf.get_stride()
    for y in range(h):
        row = src[y * stride:y * stride + w * n]
        r, g, b = row[0::n], row[1::n], row[2::n]
        a = row[3::n] if has_alpha else bytes([255]) * w
        out = bytearray(w * 4)
        if has_alpha:
            out[0::4] = bytes((bb * aa + 127) // 255 for bb, aa in zip(b, a))
            out[1::4] = bytes((gg * aa + 127) // 255 for gg, aa in zip(g, a))
            out[2::4] = bytes((rr * aa + 127) // 255 for rr, aa in zip(r, a))
        else:
            out[0::4], out[1::4], out[2::4] = b, g, r
        out[3::4] = a
        dst[y * dstride:y * dstride + w * 4] = out
    surf.mark_dirty()
    return surf


def pixbuf_from_image_data(data):
    """freedesktop `image-data` hint: (iiibiiay)."""
    try:
        w, h, stride, alpha, bits, channels, raw = data
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(raw)), GdkPixbuf.Colorspace.RGB,
                                             bool(alpha), int(bits), int(w), int(h), int(stride))
        return pb
    except Exception:
        return None


def icon_surface(name, size):
    """Cairo surface for an icon name / path, or None."""
    if not name:
        return None
    key = (name, size)
    if key in _icon_cache:
        return _icon_cache[key]
    surf = None
    try:
        path = None
        if name.startswith('file://'):
            path = GLib.filename_from_uri(name)[0]
        elif name.startswith('/'):
            path = name
        else:
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            for candidate in (name, name.lower()):
                if theme.has_icon(candidate):
                    info = theme.lookup_icon(candidate, None, size, 2, Gtk.TextDirection.NONE, 0)
                    f = info.get_file()
                    if f is not None:
                        path = f.get_path()
                        break
        if path and os.path.exists(path):
            pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size * 2, size * 2)
            surf = _surface_from_pixbuf(pb)
    except Exception:
        surf = None
    _icon_cache[key] = surf
    return surf


_app_icon_cache = {}


def _names_from_gicon(gicon):
    out = []
    try:
        if isinstance(gicon, Gio.ThemedIcon):
            out += list(gicon.get_names())
        elif isinstance(gicon, Gio.FileIcon):
            f = gicon.get_file()
            if f is not None and f.get_path():
                out.append(f.get_path())
    except Exception:
        pass
    return out


def _desktop_info(app, desktop):
    """Find the .desktop entry for a notification: desktop-entry hint first, then by app name."""
    ids = []
    if desktop:
        ids += [desktop if desktop.endswith('.desktop') else desktop + '.desktop']
    for ident in ids:
        try:
            info = Gio.DesktopAppInfo.new(ident)
            if info is not None:
                return info
        except Exception:
            pass
    for q in filter(None, {app, app.lower(), app.replace(' ', '-').lower()}):
        try:
            for group in Gio.DesktopAppInfo.search(q):
                for ident in group:
                    info = Gio.DesktopAppInfo.new(ident)
                    if info is None or info.get_icon() is None:
                        continue
                    # the search is fuzzy: only accept an exact name or an id that starts with the name
                    if info.get_name().lower() == q.lower() or ident.lower().startswith(q.lower()):
                        return info
        except Exception:
            pass
    return None


def app_icon_surface(n, size):
    """Best icon we can find for a notification, or None (the caller falls back to a letter)."""
    key = (n.icon, n.desktop, n.app, size)
    if key in _app_icon_cache:
        return _app_icon_cache[key]
    surf = None
    candidates = [n.icon] if n.icon else []
    if not candidates or icon_surface(n.icon, size) is None:
        candidates = [n.icon] if n.icon else []
        info = _desktop_info(n.app or '', n.desktop or '')
        if info is not None:
            candidates += _names_from_gicon(info.get_icon())
        if n.desktop:
            candidates.append(n.desktop)
        if n.app:
            candidates += [n.app, n.app.lower(), n.app.lower().replace(' ', '-')]
    for name in candidates:
        surf = icon_surface(name, size)
        if surf is not None:
            break
    if len(_app_icon_cache) > 200:
        _app_icon_cache.clear()
    _app_icon_cache[key] = surf
    return surf


def pixbuf_surface(pb, size):
    try:
        w, h = pb.get_width(), pb.get_height()
        k = (size * 2) / max(w, h)
        pb2 = pb.scale_simple(max(1, int(w * k)), max(1, int(h * k)), GdkPixbuf.InterpType.BILINEAR)
        return _surface_from_pixbuf(pb2)
    except Exception:
        return None


def draw_surface_fit(cr, surf, cx, cy, size):
    """Draw a (2x oversampled) surface centred on (cx, cy), fitted to `size`."""
    w, h = surf.get_width(), surf.get_height()
    k = size / max(w, h)
    cr.save()
    cr.translate(cx - w * k / 2, cy - h * k / 2)
    cr.scale(k, k)
    cr.set_source_surface(surf, 0, 0)
    cr.paint()
    cr.restore()


def avatar_colour(name):
    h = int(hashlib.md5((name or '?').encode()).hexdigest()[:6], 16)
    hue = (h % 360) / 360.0
    # pleasant pastel from hue
    import colorsys
    return colorsys.hls_to_rgb(hue, .62, .62)


def initial(name):
    for ch in (name or '?'):
        if ch.isalnum():
            return ch.upper()
    return '•'


# ======================================================================= liquid glass
# One switch (~/.local/state/desk-style/style.json) turns every island from black into liquid glass:
# a blurred snapshot of what is behind the island, a dark tint, and bright specular rims.
STYLE_FILE = Path.home() / '.local/state/desk-style/style.json'
_style = {'t': 0.0, 'mt': None, 'v': 'black'}
_glass = {'surf': None, 'sx': 1.0, 'sy': 1.0, 'ox': 0.0, 'oy': 0.0, 'lum': .3, 'at': 0.0}


def style():
    """'black' (default) or 'glass'; re-read at most once a second."""
    now = time.monotonic()
    if now - _style['t'] > 1.0:
        _style['t'] = now
        try:
            mt = STYLE_FILE.stat().st_mtime
            if mt != _style['mt']:
                _style['mt'] = mt
                v = json.loads(STYLE_FILE.read_text()).get('style', 'black')
                _style['v'] = v if v in ('black', 'glass') else 'black'
        except (OSError, ValueError):
            _style['v'] = 'black'
    return _style['v']


def glass_origin(ox, oy):
    """Screen position (logical px) of the window's top-left corner, so the snapshot lines up."""
    _glass['ox'], _glass['oy'] = float(ox), float(oy)


def glass_prepare(force=False):
    """Take and blur a snapshot of the screen. Call it just before the island window is shown."""
    if style() != 'glass':
        return False
    if not force and _glass['surf'] is not None and time.monotonic() - _glass['at'] < .6:
        return True
    try:
        import io
        import subprocess
        out = json.loads(subprocess.check_output(['niri', 'msg', '--json', 'focused-output'], timeout=2).decode())
        name, lw = out.get('name'), float(out['logical']['width'])
        lh = float(out['logical']['height'])
        png = subprocess.check_output(['grim', '-o', name, '-s', '0.10', '-'], timeout=3, stderr=subprocess.DEVNULL)
        small = cairo.ImageSurface.create_from_png(io.BytesIO(png))
    except Exception:
        return False
    w, h = small.get_width(), small.get_height()
    # blur: shrink hard (area average) then let bilinear scaling smooth it back up
    bw, bh = max(8, w // 3), max(6, h // 3)
    blur = cairo.ImageSurface(cairo.FORMAT_ARGB32, bw, bh)
    bc = cairo.Context(blur)
    bc.scale(bw / w, bh / h)
    p = cairo.SurfacePattern(small)
    p.set_filter(cairo.FILTER_BEST)
    bc.set_source(p)
    bc.paint()
    blur.flush()
    d = bytes(blur.get_data())
    st = blur.get_stride()
    tot = 0.0
    for i in range(0, bh * st, 4 * 3):
        tot += (d[i + 2] * .3 + d[i + 1] * .59 + d[i] * .11) / 255
    _glass.update(surf=blur, sx=lw / bw, sy=lh / bh, lw=lw, lh=lh, lum=tot / max(1, bh * st // 12), at=time.monotonic())
    return True


def _backdrop_lum(x1, y1, x2, y2, M):
    """Average brightness (0..1) of the blurred snapshot under a user-space box, sampled on a coarse grid."""
    surf = _glass['surf']
    if surf is None:
        return .3
    d = surf.get_data()
    st, bw, bh = surf.get_stride(), surf.get_width(), surf.get_height()
    tot, n = 0.0, 0
    for fx in (.15, .5, .85):
        for fy in (.15, .5, .85):
            px, py = M.transform_point(x1 + (x2 - x1) * fx, y1 + (y2 - y1) * fy)
            ix = int(clamp((px + _glass['ox']) / _glass['sx'], 0, bw - 1))
            iy = int(clamp((py + _glass['oy']) / _glass['sy'], 0, bh - 1))
            o = iy * st + ix * 4
            tot += (d[o + 2] * .3 + d[o + 1] * .59 + d[o] * .11) / 255
            n += 1
    return tot / max(1, n)


def panel_fill(cr, black=(.016, .016, .022), rim=.07):
    """Fill and rim the CURRENT PATH as an island: black, or liquid glass when the style says so.

    Replaces the usual "set_source_rgb(black); fill_preserve(); set_source_rgba(1,1,1,.07); stroke()" and leaves no path.
    """
    if style() != 'glass' or _glass['surf'] is None:
        cr.set_source_rgb(*black)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, rim)
        cr.set_line_width(1)
        cr.stroke()
        return
    x1, y1, x2, y2 = cr.path_extents()
    w, h = max(1.0, x2 - x1), max(1.0, y2 - y1)
    M = cr.get_matrix()
    lum = _backdrop_lum(x1, y1, x2, y2, M)
    cr.save()
    cr.clip_preserve()
    # 1. the blurred backdrop, in device space so it lines up with the screen
    cr.save()
    cr.set_matrix(cairo.Matrix())
    cr.translate(-_glass['ox'], -_glass['oy'])
    cr.scale(_glass['sx'], _glass['sy'])
    pat = cairo.SurfacePattern(_glass['surf'])
    pat.set_filter(cairo.FILTER_BILINEAR)
    pat.set_extend(cairo.EXTEND_PAD)
    cr.set_source(pat)
    cr.paint()
    cr.restore()
    # 2. tint: darker over a bright backdrop so white text stays readable
    tint = clamp(.30 + .42 * lum, .30, .66)
    cr.set_source_rgba(.045, .055, .09, tint)
    cr.paint()
    # 3. soft white wash, strongest at the top, like light caught in the glass
    wash = cairo.LinearGradient(0, y1, 0, y2)
    wash.add_color_stop_rgba(0, 1, 1, 1, .16)
    wash.add_color_stop_rgba(.45, 1, 1, 1, .035)
    wash.add_color_stop_rgba(1, 1, 1, 1, .07)
    cr.set_source(wash)
    cr.paint()
    # 4. specular bloom near the top-left corner
    bloom = cairo.RadialGradient(x1 + w * .18, y1 + h * .06, 0, x1 + w * .18, y1 + h * .06, max(w, h) * .55)
    bloom.add_color_stop_rgba(0, 1, 1, 1, .20)
    bloom.add_color_stop_rgba(1, 1, 1, 1, 0)
    cr.set_source(bloom)
    cr.paint()
    # 5. inner glow along the rim (half of this stroke falls outside the clip)
    cr.set_line_width(7)
    cr.set_source_rgba(1, 1, 1, .075)
    cr.stroke_preserve()
    cr.restore()
    # 6. the bright rim itself: bright top-left, fading, a faint return at the bottom-right
    rimg = cairo.LinearGradient(x1, y1, x2, y2)
    rimg.add_color_stop_rgba(0, 1, 1, 1, .70)
    rimg.add_color_stop_rgba(.35, 1, 1, 1, .16)
    rimg.add_color_stop_rgba(.7, 1, 1, 1, .10)
    rimg.add_color_stop_rgba(1, 1, 1, 1, .34)
    cr.set_source(rimg)
    cr.set_line_width(1.2)
    cr.stroke_preserve()
    cr.set_source_rgba(0, 0, 0, .25)       # hairline outside so the glass edge holds on bright wallpapers
    cr.set_line_width(.5)
    cr.stroke()


def glass_flat(cr, tint=.62):
    """Liquid glass without a backdrop snapshot, for cards that move around (notifications): a translucent dark
    body, a soft white wash and a bright rim. Fills the current path and leaves it for the caller's own rim."""
    x1, y1, x2, y2 = cr.path_extents()
    w, h = max(1.0, x2 - x1), max(1.0, y2 - y1)
    cr.save()
    cr.clip_preserve()
    cr.set_source_rgba(.045, .055, .09, tint)
    cr.paint()
    wash = cairo.LinearGradient(0, y1, 0, y2)
    wash.add_color_stop_rgba(0, 1, 1, 1, .17)
    wash.add_color_stop_rgba(.5, 1, 1, 1, .04)
    wash.add_color_stop_rgba(1, 1, 1, 1, .08)
    cr.set_source(wash)
    cr.paint()
    bloom = cairo.RadialGradient(x1 + w * .15, y1 + h * .08, 0, x1 + w * .15, y1 + h * .08, max(w, h) * .6)
    bloom.add_color_stop_rgba(0, 1, 1, 1, .20)
    bloom.add_color_stop_rgba(1, 1, 1, 1, 0)
    cr.set_source(bloom)
    cr.paint()
    cr.set_line_width(6)
    cr.set_source_rgba(1, 1, 1, .06)
    cr.stroke_preserve()
    cr.restore()
    rim = cairo.LinearGradient(x1, y1, x2, y2)
    rim.add_color_stop_rgba(0, 1, 1, 1, .70)
    rim.add_color_stop_rgba(.4, 1, 1, 1, .16)
    rim.add_color_stop_rgba(.7, 1, 1, 1, .10)
    rim.add_color_stop_rgba(1, 1, 1, 1, .34)
    cr.set_source(rim)
    cr.set_line_width(1.1)
    cr.stroke_preserve()

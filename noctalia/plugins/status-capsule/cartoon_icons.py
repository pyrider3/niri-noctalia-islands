"""Cute animated cartoon icons for the status capsule.

Every icon is drawn centred on (0, 0) in roughly an 18x18 box and takes the
running time `t` (seconds) so it is always moving: bobbing, blinking, spinning
rays, travelling waves.
"""
import math

import cairo

INK = (.25, .15, .2)


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _blink(t, phase, period=3.7):
    return .1 if (t + phase) % period < .13 else 1.0


def _eyes(c, y, gap, r, open_, closed=False):
    c.set_source_rgb(*INK)
    for sx in (-gap, gap):
        if closed:
            c.set_line_width(.9)
            c.set_line_cap(cairo.LINE_CAP_ROUND)
            c.new_sub_path()
            c.arc(sx, y + .4, r, math.radians(200), math.radians(340))
            c.stroke()
        else:
            c.save()
            c.translate(sx, y)
            c.scale(1, max(.1, open_))
            c.new_sub_path()
            c.arc(0, 0, r, 0, 2 * math.pi)
            c.restore()
            c.fill()
            # tiny sparkle
            if open_ > .5:
                c.set_source_rgba(1, 1, 1, .9)
                c.new_sub_path()
                c.arc(sx + r * .35, y - r * .35, r * .32, 0, 2 * math.pi)
                c.fill()
                c.set_source_rgb(*INK)


def _blush(c, y, gap, rx=1.5, ry=.9):
    c.set_source_rgba(1, .42, .52, .5)
    for sx in (-gap, gap):
        c.save()
        c.translate(sx, y)
        c.scale(rx, ry)
        c.new_sub_path()
        c.arc(0, 0, 1, 0, 2 * math.pi)
        c.restore()
        c.fill()


def _smile(c, y, w, depth=1.0):
    c.set_source_rgb(*INK)
    c.set_line_width(.9)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.new_sub_path()
    c.move_to(-w, y)
    c.curve_to(-w * .5, y + depth * 1.4, w * .5, y + depth * 1.4, w, y)
    c.stroke()


def _open_mouth(c, y, rx, ry):
    c.set_source_rgb(*INK)
    c.save()
    c.translate(0, y)
    c.scale(rx, max(.2, ry))
    c.new_sub_path()
    c.arc(0, 0, 1, 0, 2 * math.pi)
    c.restore()
    c.fill()
    c.set_source_rgb(1, .55, .6)
    c.save()
    c.translate(0, y + ry * .45)
    c.scale(rx * .6, max(.1, ry * .45))
    c.new_sub_path()
    c.arc(0, 0, 1, 0, 2 * math.pi)
    c.restore()
    c.fill()


def _shine(c, x, y, r):
    c.set_source_rgba(1, 1, 1, .38)
    c.save()
    c.translate(x, y)
    c.scale(r, r * .7)
    c.new_sub_path()
    c.arc(0, 0, 1, 0, 2 * math.pi)
    c.restore()
    c.fill()


def bluetooth(c, s, t):
    on = s.bt_on
    conn = s.bt_n > 0
    body = _rgb('#58AEFF') if on else _rgb('#9AA8B8')
    bob = math.sin(t * (4.2 if conn else 2.4)) * (1.1 if conn else .55)
    squish = 1 + (.06 * math.sin(t * 8.4) if conn else .02 * math.sin(t * 2.4))
    c.save()
    c.translate(-1.2, 2.6 + bob)
    c.scale(1 / squish, squish)
    c.set_source_rgb(*body)
    c.new_sub_path()
    c.arc(0, 0, 6.4, 0, 2 * math.pi)
    c.fill()
    _shine(c, -2.4, -3.4, 2.0)
    if on:
        _eyes(c, -.8, 2.1, .95, _blink(t, 0.3))
        if conn:
            _open_mouth(c, 2.2, 1.3, .9 + .25 * math.sin(t * 8.4))
        else:
            _smile(c, 1.9, 1.4)
        _blush(c, 1.7, 3.9, 1.1, .7)
    else:
        _eyes(c, -.6, 2.1, 1.1, 1, closed=True)
        _open_mouth(c, 2.3, .7, .5)
    c.restore()
    if on:
        # little bluetooth badge floating next to it
        bx, by = 6.4, -5.2 + math.sin(t * 2.4 + 1) * .8
        c.set_source_rgba(1, 1, 1, .96)
        c.new_sub_path()
        c.arc(bx, by, 4.2, 0, 2 * math.pi)
        c.fill()
        c.set_source_rgb(*body)
        c.set_line_width(1.1)
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        c.set_line_join(cairo.LINE_JOIN_ROUND)
        k = .4
        pts = [(-3.8, -3.5), (3.8, 3.5), (0, 7), (0, -7), (3.8, -3.5), (-3.8, 3.5)]
        c.move_to(bx + pts[0][0] * k, by + pts[0][1] * k)
        for px, py in pts[1:]:
            c.line_to(bx + px * k, by + py * k)
        c.stroke()
    else:
        # sleepy "z z"
        c.select_font_face('Noto Sans CJK SC', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        for i in range(2):
            ph = ((t * .7) + i * .5) % 1.0
            c.set_font_size(4.2 + 2 * ph)
            c.set_source_rgba(.45, .55, .7, 1 - ph)
            c.move_to(4.5 + ph * 2.5, -2.5 - ph * 6)
            c.show_text('z')


def wifi(c, s, t):
    sig = s.wifi
    level = 0 if sig is None else (3 if sig >= 66 else 2 if sig >= 36 else 1)
    col = _rgb('#2FD6A6') if sig is not None else _rgb('#9AA8B8')
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_width(1.8)
    cy = 1.0
    for i, r in enumerate((4.8, 7.6, 10.4)):
        if level > i:
            a = .6 + .4 * max(0, math.sin(t * 4.2 - i * 1.2)) ** 2
        else:
            a = .2
        c.set_source_rgba(col[0], col[1], col[2], a)
        c.new_sub_path()
        c.arc(0, cy, r, -math.radians(128), -math.radians(52))
        c.stroke()
    bob = math.sin(t * 3.0 + .6) * .5
    c.save()
    c.translate(0, 5.6 + bob)
    c.set_source_rgb(*col)
    c.new_sub_path()
    c.arc(0, 0, 3.9, 0, 2 * math.pi)
    c.fill()
    _shine(c, -1.3, -1.9, 1.3)
    if sig is not None:
        _eyes(c, -.5, 1.4, .75, _blink(t, 1.1))
        _smile(c, 1.2, 1.0, .8)
        _blush(c, 1.0, 2.5, .8, .5)
    else:
        _eyes(c, -.3, 1.4, .8, 1, closed=True)
        c.set_source_rgb(*INK)
        c.set_line_width(.8)
        c.move_to(-.9, 1.7); c.line_to(.9, 1.7); c.stroke()
    c.restore()


def volume(c, s, t, level):
    muted = s.muted or level <= .001
    body = _rgb('#FF84AE') if not muted else _rgb('#C9A9B7')
    horn = tuple(min(1, v * .85 + .15) for v in body)
    bob = math.sin(t * 3.4) * .6
    c.save()
    c.translate(-2.2, bob)
    # horn
    c.set_source_rgb(*horn)
    c.move_to(2.0, -3.2); c.line_to(6.2, -6.0); c.line_to(6.2, 6.0); c.line_to(2.0, 3.2)
    c.close_path()
    c.fill()
    # face body
    c.set_source_rgb(*body)
    c.new_sub_path()
    r, x0, y0, w, h = 4.4, -7.4, -6.2, 10.0, 12.4
    c.arc(x0 + w - r, y0 + r, r, -math.pi / 2, 0)
    c.arc(x0 + w - r, y0 + h - r, r, 0, math.pi / 2)
    c.arc(x0 + r, y0 + h - r, r, math.pi / 2, math.pi)
    c.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
    c.close_path()
    c.fill()
    _shine(c, -4.6, -3.7, 1.9)
    if muted:
        _eyes(c, -1.3, 2.1, 1.0, 1, closed=True)
        c.set_source_rgb(*INK)
        c.set_line_width(.9)
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        c.move_to(-4.7, 2.7); c.line_to(-2.9, 2.7); c.stroke()
    else:
        _eyes(c, -1.3, 2.1, .95, _blink(t, 2.0))
        sing = .55 + .45 * abs(math.sin(t * 7.0))
        _open_mouth(c, 2.5, 1.3, .5 + 1.5 * level * sing)
        _blush(c, 1.4, 3.8, 1.0, .65)
    c.restore()
    if not muted:
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        c.set_line_width(1.6)
        for i, (r, lo) in enumerate(((3.2, 0.0), (6.0, .42))):
            lit = _clamp((level - lo) / .16)
            a = (.25 + .75 * max(0, math.sin(t * 5.0 - i * 1.3)) ** 2) * (.35 + .65 * lit)
            c.set_source_rgba(body[0], body[1], body[2], a)
            c.new_sub_path()
            c.arc(4.2, bob, r, -math.radians(48), math.radians(48))
            c.stroke()


def brightness(c, s, t, level):
    sun = _rgb('#FFD24A')
    ray = _rgb('#FFAE2B')
    pulse = 1 + .045 * math.sin(t * 3.2)
    c.save()
    c.rotate(t * .55)
    c.set_source_rgb(*ray)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_width(1.6)
    length = 1.2 + 2.5 * level + .35 * math.sin(t * 5.0)
    for i in range(8):
        c.save()
        c.rotate(i * math.pi / 4)
        c.move_to(0, -6.0)
        c.line_to(0, -(6.0 + length))
        c.restore()
    c.stroke()
    c.restore()
    c.save()
    c.scale(pulse, pulse)
    c.set_source_rgb(*sun)
    c.new_sub_path()
    c.arc(0, 0, 4.9, 0, 2 * math.pi)
    c.fill()
    _shine(c, -1.8, -2.3, 1.6)
    if level < .15:
        _eyes(c, -.6, 1.8, .9, 1, closed=True)
        _open_mouth(c, 1.9, .6, .45)
    else:
        _eyes(c, -.7, 1.8, .85, _blink(t, 0.7))
        _smile(c, 1.3, 1.3, .9)
    _blush(c, 1.2, 3.1, .9, .55)
    c.restore()

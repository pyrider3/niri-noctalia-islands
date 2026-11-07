"""Cute animated sun / moon face shared by the bar clock and the island."""
import math

TAU = 2 * math.pi


def sun_amount(hour):
    """1 = day (sun), 0 = night (moon), with ~1 h cross-fades at dawn and dusk."""
    h = hour % 24
    if h < 5.5 or h >= 19.0:
        return 0.0
    if h < 6.5:
        return h - 5.5
    if h < 17.5:
        return 1.0
    return 19.0 - h if h > 18.0 else 1.0 - (h - 17.5) * .0


def warmth(hour):
    """0..1: how orange the sun looks (dawn / dusk)."""
    h = hour % 24
    d = min(abs(h - 6.2), abs(h - 18.0))
    return max(0.0, 1 - d / 1.8)


def _eye(c, x, y, r, blink, sleepy=False):
    if sleepy:
        c.new_path()
        c.arc(x, y + r * .2, r * 1.1, math.pi * .12, math.pi * .88)
        c.set_line_width(max(.8, r * .55))
        c.set_line_cap(1)
        c.stroke()
        return
    c.save()
    c.translate(x, y)
    c.scale(1, max(.12, 1 - blink))
    c.arc(0, 0, r, 0, TAU)
    c.fill()
    c.restore()


def draw_sun(c, cx, cy, r, t, blink, warm=0.0, alpha=1.0, look=0.0):
    c.save()
    c.translate(cx, cy)
    body = (1.0, .80 - .22 * warm, .24 - .06 * warm)
    ray = (1.0, .72 - .22 * warm, .2)
    # rays
    n = 8
    for i in range(n):
        a = t * .6 + i * TAU / n
        pulse = .5 + .5 * math.sin(t * 2.2 + i * 1.3)
        r0 = r * (.78 + .03 * pulse)
        r1 = r * (.98 + .14 * pulse)
        c.set_source_rgba(*ray, alpha * .95)
        c.set_line_width(max(1.0, r * .13))
        c.set_line_cap(1)
        c.move_to(math.cos(a) * r0, math.sin(a) * r0)
        c.line_to(math.cos(a) * r1, math.sin(a) * r1)
        c.stroke()
    g = None
    c.set_source_rgba(*body, alpha)
    c.arc(0, 0, r * .66, 0, TAU)
    c.fill()
    # face
    c.set_source_rgba(.28, .16, .06, alpha)
    ex = r * .23
    _eye(c, -ex + look * r * .05, -r * .08, r * .095, blink)
    _eye(c, ex + look * r * .05, -r * .08, r * .095, blink)
    c.set_line_width(max(.8, r * .075))
    c.set_line_cap(1)
    c.arc(look * r * .03, r * .06, r * .17, math.pi * .18, math.pi * .82)
    c.stroke()
    c.set_source_rgba(1, .42, .42, alpha * .55)
    for sx in (-1, 1):
        c.arc(sx * r * .4, r * .12, r * .08, 0, TAU)
        c.fill()
    c.restore()


def draw_moon(c, cx, cy, r, t, blink, alpha=1.0):
    c.save()
    c.translate(cx, cy)
    # twinkling stars
    for i, (sx, sy, ph, sz) in enumerate(((.86, -.62, 0.0, .17), (.62, .78, 2.1, .12), (-.92, -.36, 4.0, .1))):
        s = .5 + .5 * math.sin(t * 2.0 + ph)
        rr = r * sz * (.5 + s)
        c.set_source_rgba(1, .95, .7, alpha * (.35 + .65 * s))
        x, y = sx * r, sy * r
        c.move_to(x, y - rr)
        c.line_to(x + rr * .28, y - rr * .28)
        c.line_to(x + rr, y)
        c.line_to(x + rr * .28, y + rr * .28)
        c.line_to(x, y + rr)
        c.line_to(x - rr * .28, y + rr * .28)
        c.line_to(x - rr, y)
        c.line_to(x - rr * .28, y - rr * .28)
        c.close_path()
        c.fill()
    # crescent (disc minus offset disc), gently rocking
    c.save()
    c.rotate(math.sin(t * .9) * .12)
    c.push_group()
    c.set_source_rgb(.98, .93, .66)
    c.arc(0, 0, r * .82, 0, TAU)
    c.fill()
    c.set_operator(9)   # DEST_OUT
    c.arc(r * .46, -r * .22, r * .66, 0, TAU)
    c.fill()
    c.pop_group_to_source()
    c.paint_with_alpha(alpha)
    c.restore()
    # sleepy face on the crescent
    c.set_source_rgba(.4, .32, .12, alpha)
    c.set_line_width(max(.8, r * .08))
    c.set_line_cap(1)
    c.arc(-r * .42, -r * .02, r * .1, math.pi * .1, math.pi * .9)
    c.stroke()
    c.arc(-r * .5, r * .3, r * .1, math.pi * 1.1, math.pi * 1.9)
    c.stroke()
    # floating z
    zt = (t * .5) % 1.0
    c.set_source_rgba(.95, .92, .8, alpha * math.sin(zt * math.pi))
    c.set_line_width(max(.7, r * .07))
    zx, zy, zs = r * .35 + zt * r * .3, -r * .55 - zt * r * .5, r * .13
    c.move_to(zx - zs, zy - zs)
    c.line_to(zx + zs, zy - zs)
    c.line_to(zx - zs, zy + zs)
    c.line_to(zx + zs, zy + zs)
    c.stroke()
    c.restore()


def draw_weather_icon(c, cx, cy, r, t, sun, blink, hour, alpha=1.0, look=0.0):
    """Cross-fade between sun and moon (sun in [0,1]); each flips/scales in as the other leaves."""
    if sun > .01:
        c.save()
        c.translate(cx, cy)
        s = .55 + .45 * sun
        c.scale(s, s)
        c.rotate((1 - sun) * -.9)
        draw_sun(c, 0, 0, r, t, blink, warmth(hour), alpha * min(1.0, sun * 1.4), look)
        c.restore()
    if sun < .99:
        m = 1 - sun
        c.save()
        c.translate(cx, cy)
        s = .55 + .45 * m
        c.scale(s, s)
        c.rotate(sun * .9)
        draw_moon(c, 0, 0, r, t, blink, alpha * min(1.0, m * 1.4))
        c.restore()


def draw_tomato(c, cx, cy, r, t, mood='idle', blink=0.0, alpha=1.0, tint=(1.0, .36, .3)):
    """Little tomato; mood: focus (determined), rest (happy, closed eyes), idle."""
    c.save()
    c.translate(cx, cy + math.sin(t * 2.2) * r * .03)
    sq = 1 + math.sin(t * 2.2) * .012
    c.scale(sq, 1 / sq)
    # body
    c.save()
    c.scale(1, .9)
    import cairo
    g = cairo.RadialGradient(-r * .3, -r * .35, r * .1, 0, 0, r * 1.05)
    g.add_color_stop_rgba(0, min(1, tint[0] + .0), min(1, tint[1] + .28), min(1, tint[2] + .25), alpha)
    g.add_color_stop_rgba(1, tint[0] * .86, tint[1] * .62, tint[2] * .62, alpha)
    c.set_source(g)
    c.arc(0, 0, r, 0, TAU)
    c.fill()
    c.restore()
    # leaf star + stem
    c.save()
    c.translate(0, -r * .78)
    c.rotate(math.sin(t * 1.6) * .08)
    c.set_source_rgba(.32, .72, .34, alpha)
    for i in range(5):
        a = -math.pi / 2 + (i - 2) * .62
        c.save()
        c.rotate(a + math.pi / 2)
        c.move_to(0, 0)
        c.curve_to(r * .22, -r * .05, r * .26, -r * .3, 0, -r * .42)
        c.curve_to(-r * .26, -r * .3, -r * .22, -r * .05, 0, 0)
        c.fill()
        c.restore()
    c.set_source_rgba(.25, .55, .26, alpha)
    c.set_line_width(max(1.0, r * .09))
    c.set_line_cap(1)
    c.move_to(0, -r * .02)
    c.line_to(r * .08, -r * .3)
    c.stroke()
    c.restore()
    # face
    c.set_source_rgba(.25, .08, .06, alpha)
    ex, ey = r * .34, -r * .02
    if mood == 'rest':
        c.set_line_width(max(1.0, r * .09))
        c.set_line_cap(1)
        for sx in (-1, 1):
            c.arc(sx * ex, ey + r * .06, r * .12, math.pi * 1.1, math.pi * 1.9)
            c.stroke()
        c.arc(0, r * .16, r * .2, math.pi * .1, math.pi * .9)
        c.set_source_rgba(.25, .08, .06, alpha)
        c.fill_preserve()
        c.stroke()
    else:
        for sx in (-1, 1):
            c.save()
            c.translate(sx * ex, ey)
            c.scale(1, max(.12, 1 - blink))
            c.arc(0, 0, r * .095, 0, TAU)
            c.fill()
            c.restore()
        if mood == 'focus':
            c.set_line_width(max(1.0, r * .08))
            c.set_line_cap(1)
            for sx in (-1, 1):
                c.move_to(sx * ex - sx * r * .2, ey - r * .22 - sx * r * .06 * -1)
                c.line_to(sx * ex + sx * r * .12, ey - r * .14 + sx * r * .06 * -1)
            c.stroke()
            c.move_to(-r * .13, r * .22)
            c.line_to(r * .13, r * .22)
            c.stroke()
        else:
            c.set_line_width(max(1.0, r * .08))
            c.set_line_cap(1)
            c.arc(0, r * .1, r * .15, math.pi * .15, math.pi * .85)
            c.stroke()
    c.set_source_rgba(1, .7, .7, alpha * .45)
    for sx in (-1, 1):
        c.arc(sx * r * .58, r * .16, r * .09, 0, TAU)
        c.fill()
    c.restore()


# ------------------------------------------------------------------ weather
def _cloud_path(c, r):
    for (x, y, rr) in ((-r * .38, r * .22, r * .36), (r * .0, r * .02, r * .46), (r * .42, r * .24, r * .32)):
        c.new_sub_path()
        c.arc(x, y, rr, 0, TAU)
    c.rectangle(-r * .38, r * .22, r * .8, r * .36)


def draw_cloud(c, cx, cy, r, t, tone=(.96, .97, 1.0), face=True, blink=0.0, alpha=1.0, mood='happy', bob=True):
    c.save()
    c.translate(cx, cy + (math.sin(t * 1.6) * r * .04 if bob else 0))
    c.set_source_rgba(*tone, alpha)
    _cloud_path(c, r)
    c.fill()
    if face:
        c.set_source_rgba(.25, .28, .4, alpha)
        for sx in (-1, 1):
            c.save()
            c.translate(sx * r * .17, r * .3)
            c.scale(1, max(.12, 1 - blink))
            c.arc(0, 0, r * .07, 0, TAU)
            c.fill()
            c.restore()
        c.set_line_width(max(.8, r * .06))
        c.set_line_cap(1)
        if mood == 'happy':
            c.arc(0, r * .33, r * .1, math.pi * .15, math.pi * .85)
        elif mood == 'sad':
            c.arc(0, r * .5, r * .09, math.pi * 1.15, math.pi * 1.85)
        else:   # surprised
            c.arc(0, r * .42, r * .05, 0, TAU)
        c.stroke()
        c.set_source_rgba(1, .6, .65, alpha * .4)
        for sx in (-1, 1):
            c.arc(sx * r * .34, r * .42, r * .06, 0, TAU)
            c.fill()
    c.restore()


def _drops(c, cx, cy, r, t, alpha, snow=False, n=3):
    for i in range(n):
        ph = (t * (.9 if snow else 1.6) + i / n) % 1.0
        x = cx + (i - (n - 1) / 2) * r * .36 + (math.sin(t * 2 + i) * r * .08 if snow else 0)
        y = cy + r * .1 + ph * r * .75
        a = alpha * math.sin(ph * math.pi)
        c.new_path()
        if snow:
            c.set_source_rgba(1, 1, 1, a)
            c.arc(x, y, r * .075, 0, TAU)
            c.fill()
        else:
            c.set_source_rgba(.45, .72, 1, a)
            c.set_line_width(max(1.0, r * .09))
            c.set_line_cap(1)
            c.move_to(x - r * .05, y - r * .1)
            c.line_to(x, y + r * .06)
            c.stroke()


def draw_condition(c, cx, cy, r, t, cond, sun, blink, hour, alpha=1.0, look=0.0):
    """Weather icon: cond is one of clear / partly / cloud / fog / drizzle / rain / snow / storm; `sun` is
    the local day (1) or night (0) amount."""
    night = sun < .5
    cloud_tone = (.96, .97, 1.0) if not night else (.8, .84, .96)
    if cond == 'clear':
        draw_weather_icon(c, cx, cy, r, t, sun, blink, hour, alpha, look)
    elif cond == 'partly':
        draw_weather_icon(c, cx + r * .26, cy - r * .3, r * .66, t, sun, blink, hour, alpha, look)
        draw_cloud(c, cx - r * .08, cy + r * .12, r * .82, t, cloud_tone, True, blink, alpha)
    elif cond == 'cloud':
        draw_cloud(c, cx + r * .22, cy - r * .22, r * .6, t + 1, tuple(v * .86 for v in cloud_tone), False, 0, alpha * .9)
        draw_cloud(c, cx - r * .02, cy + r * .1, r * .9, t, cloud_tone, True, blink, alpha)
    elif cond == 'fog':
        draw_cloud(c, cx, cy - r * .22, r * .8, t, (.84, .86, .92) if not night else (.7, .74, .88), True, blink, alpha)
        c.set_line_cap(1)
        c.set_line_width(max(1.2, r * .09))
        for i, w in enumerate((.7, .5, .62)):
            y = cy + r * (.46 + i * .2)
            x = math.sin(t * 1.2 + i) * r * .12
            c.set_source_rgba(.85, .88, .95, alpha * (.8 - i * .15))
            c.move_to(cx - r * w + x, y)
            c.line_to(cx + r * w + x, y)
            c.stroke()
    elif cond in ('drizzle', 'rain', 'snow'):
        tone = tuple(v * (.8 if cond == 'rain' else .9) for v in cloud_tone)
        draw_cloud(c, cx, cy - r * .22, r * .86, t, tone, True, blink, alpha, 'sad' if cond != 'snow' else 'happy')
        _drops(c, cx, cy + r * .3, r, t, alpha, snow=(cond == 'snow'), n=2 if cond == 'drizzle' else 3)
    elif cond == 'storm':
        draw_cloud(c, cx, cy - r * .22, r * .86, t, tuple(v * .62 for v in cloud_tone), True, blink, alpha, 'wow')
        flash = max(0.0, math.sin(t * 2.6)) ** 12
        c.save()
        c.translate(cx, cy + r * .42)
        c.set_source_rgba(1, .88, .3, alpha * (.55 + .45 * flash))
        c.move_to(r * .1, -r * .3)
        c.line_to(-r * .2, r * .08)
        c.line_to(-r * .02, r * .08)
        c.line_to(-r * .12, r * .46)
        c.line_to(r * .24, -r * .06)
        c.line_to(r * .05, -r * .06)
        c.close_path()
        c.fill()
        c.restore()
    else:
        draw_weather_icon(c, cx, cy, r, t, sun, blink, hour, alpha, look)

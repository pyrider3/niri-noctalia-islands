#!/usr/bin/env python3
"""Status capsule: bluetooth / Wi-Fi / volume / brightness drawn with cairo.

Fixed total width (so neighbours in the bar never shift). The hovered cell
springs open while the others compress; scroll adjusts the value under the
pointer.
"""
import json
import math
import os
import subprocess
import threading
import time
from pathlib import Path

import cairo

import cartoon_icons

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'status-capsule'
H, W, SCALE = 28, 152, 2
PAD = 4
INNER = W - 2 * PAD          # 144
BASE = INNER / 4             # 36 -> idle cell width
EXPAND = 72                  # hovered cell width
NAMES = ('bluetooth', 'wifi', 'volume', 'brightness')
ENV = dict(os.environ, LC_ALL='C')


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def rgba(value, alpha=1.0, fallback=(.93, .71, .61)):
    try:
        return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)) + (alpha,)
    except (ValueError, TypeError):
        return fallback + (alpha,)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_json(path, value):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False)
    tmp.replace(path)


def run(*argv, timeout=2):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=ENV).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


class Spring:
    """Under-damped spring: a little overshoot gives the elastic feel."""

    def __init__(self, x, omega=30.0, zeta=.62):
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
        if abs(self.x - self.t) < .015 and abs(self.v) < .04:
            self.x, self.v = self.t, 0.0

    @property
    def moving(self):
        return self.x != self.t or self.v != 0.0


class SystemState:
    """Polls the system in a thread; user actions apply optimistically."""

    def __init__(self):
        self.vol, self.muted, self.bright = 0.0, False, 1.0
        self.bt_on, self.bt_n = False, 0
        self.wifi_miss = 0
        self.wifi_on, self.bt_names = True, []
        self.wifi, self.ssid = None, ''
        self.hold = {'vol': 0.0, 'bright': 0.0}
        self.backlight = None
        for name in ('intel_backlight',):
            if (Path('/sys/class/backlight') / name).exists():
                self.backlight = Path('/sys/class/backlight') / name
        if self.backlight is None:
            found = sorted(Path('/sys/class/backlight').glob('*'))
            self.backlight = found[0] if found else None
        self.max_raw = 1
        if self.backlight:
            try:
                self.max_raw = int((self.backlight / 'max_brightness').read_text())
            except (OSError, ValueError):
                pass
        self.poll_volume()
        self.poll_brightness()
        self.poll_net()
        threading.Thread(target=self.loop, daemon=True).start()

    def poll_volume(self):
        if time.monotonic() < self.hold['vol']:
            return
        out = run('wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@')
        try:
            self.vol = float(out.split()[1])
            self.muted = '[MUTED]' in out
        except (IndexError, ValueError):
            pass

    def poll_brightness(self):
        if not self.backlight or time.monotonic() < self.hold['bright']:
            return
        try:
            self.bright = int((self.backlight / 'brightness').read_text()) / self.max_raw
        except (OSError, ValueError):
            pass

    def poll_net(self):
        show = run('bluetoothctl', 'show')
        bt_on = 'Powered: yes' in show
        names = [l.split(' ', 2)[2] for l in run('bluetoothctl', 'devices', 'Connected').splitlines()
                 if l.startswith('Device') and len(l.split(' ', 2)) > 2] if bt_on else []
        bt_n = len(names)
        wifi_on = 'enabled' in run('nmcli', 'radio', 'wifi')
        wifi, ssid = None, ''
        for line in run('nmcli', '-t', '-f', 'IN-USE,SIGNAL,SSID', 'dev', 'wifi', 'list', '--rescan', 'no').splitlines():
            if line.startswith('*:'):
                parts = line.split(':', 2)
                try:
                    wifi = int(parts[1])
                except ValueError:
                    wifi = 0
                ssid = parts[2].replace('\\:', ':') if len(parts) > 2 else ''
                break
        if wifi is None and self.wifi is not None:
            # nmcli sometimes omits the active AP mid-scan: need 3 misses in a row.
            self.wifi_miss += 1
            if self.wifi_miss < 3:
                wifi, ssid = self.wifi, self.ssid
        else:
            self.wifi_miss = 0
        self.wifi_on, self.bt_names = wifi_on, names
        self.bt_on, self.bt_n, self.wifi, self.ssid = bt_on, bt_n, wifi, ssid

    def loop(self):
        tick = 0
        while True:
            try:
                self.poll_volume()
                self.poll_brightness()
                if tick % 16 == 0:
                    self.poll_net()
            except Exception:
                pass
            tick += 1
            time.sleep(.25)

    # --- actions -------------------------------------------------------
    def set_volume(self, v):
        self.vol = clamp(v)
        self.hold['vol'] = time.monotonic() + .8
        if self.muted and self.vol > 0:
            self.muted = False
            subprocess.Popen(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', '0'])
        subprocess.Popen(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', f'{self.vol:.3f}'])

    def toggle_mute(self):
        self.muted = not self.muted
        self.hold['vol'] = time.monotonic() + .8
        subprocess.Popen(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', '1' if self.muted else '0'])

    def set_brightness(self, v):
        if not self.backlight:
            return
        self.bright = clamp(v, .01, 1.0)
        self.hold['bright'] = time.monotonic() + .8
        raw = max(1, round(self.bright * self.max_raw))
        subprocess.Popen(['busctl', 'call', 'org.freedesktop.login1', '/org/freedesktop/login1/session/auto',
                          'org.freedesktop.login1.Session', 'SetBrightness', 'ssu',
                          'backlight', self.backlight.name, str(raw)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def toggle_bluetooth(self):
        subprocess.Popen(['noctalia', 'msg', 'bluetooth-toggle'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- icons (drawn at 0,0, roughly 16x16) ---------------------------------

def icon_bluetooth(c, s, col, anim):
    on = s.bt_on
    c.save()
    c.set_line_width(1.5)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_join(cairo.LINE_JOIN_ROUND)
    pulse = .5 + .5 * math.sin(anim * 2.2) if s.bt_n else 0
    c.set_source_rgba(col[0], col[1], col[2], (1 if on else .35))
    c.scale(.9, .9)
    c.move_to(-3.8, -3.5); c.line_to(3.8, 3.5); c.line_to(0, 7); c.line_to(0, -7); c.line_to(3.8, -3.5); c.line_to(-3.8, 3.5)
    c.stroke()
    c.restore()
    if s.bt_n:
        c.arc(6.6, -5.6, 1.5 + .5 * pulse, 0, 2 * math.pi)
        c.set_source_rgba(col[0], col[1], col[2], 1)
        c.fill()
    if not on:
        c.set_line_width(1.4); c.set_line_cap(cairo.LINE_CAP_ROUND)
        c.set_source_rgba(col[0], col[1], col[2], .7)
        c.move_to(-6, 6); c.line_to(6, -6); c.stroke()


def icon_wifi(c, s, col, anim):
    sig = s.wifi
    level = 0 if sig is None else (3 if sig >= 66 else 2 if sig >= 36 else 1)
    c.save()
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_width(1.6)
    cy = 5.2
    for i, r in enumerate((4.2, 7.6, 11.0)):
        a = 1 if level > i else .24
        c.set_source_rgba(col[0], col[1], col[2], a)
        c.new_sub_path()
        c.arc(0, cy, r, -math.radians(133), -math.radians(47))
        c.stroke()
    c.set_source_rgba(col[0], col[1], col[2], 1 if sig is not None else .35)
    c.arc(0, cy, 1.35, 0, 2 * math.pi)
    c.fill()
    c.restore()


MARK = {}


def icon_volume(c, s, col, anim, vol):
    muted = s.muted or vol <= 0.001
    c.save()
    c.translate(-1.5, 0)
    # The speaker body doubles as the island's position marker: same colour, red channel off by one.
    r8 = int(round(col[0] * 255))
    r8 = r8 - 1 if r8 > 0 else 1                # red off by one (the bell uses blue, Notion green): never collides
    MARK['rgb'] = [r8, int(round(col[1] * 255)), int(round(col[2] * 255))] if not muted else None
    c.set_source_rgba(r8 / 255, col[1], col[2], .55 if muted else 1)
    c.move_to(-6.2, -2.6); c.line_to(-3.4, -2.6); c.line_to(.2, -5.8); c.line_to(.2, 5.8); c.line_to(-3.4, 2.6); c.line_to(-6.2, 2.6)
    c.close_path()
    c.fill()
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_width(1.5)
    if muted:
        c.set_source_rgba(col[0], col[1], col[2], .9)
        c.move_to(3.2, -2.8); c.line_to(8.2, 2.8); c.move_to(8.2, -2.8); c.line_to(3.2, 2.8)
        c.stroke()
    else:
        for r, lo in ((3.6, .0), (6.8, .45)):
            a = clamp((vol - lo) / .18)
            c.set_source_rgba(col[0], col[1], col[2], .22 + .78 * a)
            c.new_sub_path()
            c.arc(.2, 0, r, -math.radians(52), math.radians(52))
            c.stroke()
    c.restore()


def icon_brightness(c, s, col, anim, level):
    c.save()
    c.set_source_rgba(*col)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.set_line_width(1.5)
    core = 2.6 + 1.2 * level
    c.arc(0, 0, core, 0, 2 * math.pi)
    c.fill()
    length = .6 + 2.8 * level
    c.rotate(level * math.pi / 4 + anim * .0)
    for i in range(8):
        c.save()
        c.rotate(i * math.pi / 4)
        c.move_to(0, -(core + 2.0))
        c.line_to(0, -(core + 2.0 + length))
        c.restore()
    c.stroke()
    c.restore()


class Capsule:
    def __init__(self, system=None):
        self.sys = system or SystemState()
        self.input = {}
        self.input_mtime = None
        self.scroll_seen = self.click_seen = self.rclick_seen = None
        self.cells = [Spring(BASE) for _ in NAMES]
        self.pos = [(PAD + i * BASE, BASE) for i in range(4)]
        self.vol_disp = Spring(self.sys.vol * 100, omega=22, zeta=1.0)
        self.br_disp = Spring(self.sys.bright * 100, omega=22, zeta=1.0)
        self.prev = self.snapshot()
        self.peek = (None, 0.0)
        self.hover = None
        self.last_cell = object()
        self.anim = 0.0
        self.last_status = 0.0
        self.last_activity = 0.0

    def snapshot(self):
        s = self.sys
        return (round(s.vol, 2), s.muted, round(s.bright, 2), s.bt_on, s.bt_n, s.wifi is None, s.ssid)

    # --- input ---------------------------------------------------------
    def load_input(self):
        try:
            mtime = (STATE / 'input.json').stat().st_mtime_ns
        except OSError:
            return
        if mtime != self.input_mtime:
            self.input_mtime = mtime
            data = read_json(STATE / 'input.json')
            if data:
                self.input = data

    def hit(self, nx):
        x = nx * W
        for i, (cx, cw) in enumerate(self.pos):
            if x < cx + cw:
                return i
        return 3

    def handle_actions(self):
        d = self.input
        scroll, clicks, rclicks = d.get('scroll', 0), d.get('mclicks', 0), d.get('rclicks', 0)
        if self.scroll_seen is None:
            self.scroll_seen, self.click_seen, self.rclick_seen = scroll, clicks, rclicks
        idx = self.hover
        ds = scroll - self.scroll_seen
        self.scroll_seen = scroll
        if ds and idx is not None:
            up = -ds   # negative steps = wheel up = increase
            if NAMES[idx] == 'volume':
                self.sys.set_volume(self.sys.vol + .02 * up)
                self.peek = (idx, time.monotonic() + 1.2)
            elif NAMES[idx] == 'brightness':
                self.sys.set_brightness(self.sys.bright + .04 * up)
                self.peek = (idx, time.monotonic() + 1.2)
        dc = clicks - self.click_seen
        self.click_seen = clicks
        if dc and idx is not None and NAMES[idx] == 'volume':
            self.sys.toggle_mute()
        dr = rclicks - self.rclick_seen
        self.rclick_seen = rclicks
        if dr and idx is not None and NAMES[idx] == 'bluetooth':
            self.sys.toggle_bluetooth()

    # --- animation -----------------------------------------------------
    def step(self, delta, now):
        self.load_input()
        mono = time.monotonic()
        hovered = bool(self.input.get('hovered'))
        self.hover = self.hit(clamp(self.input.get('x', 0))) if hovered else None
        if self.hover != self.last_cell:
            # Tell the widget which cell the pointer is on so a click opens that cell's panel.
            self.last_cell = self.hover
            try:
                save_json(STATE / 'cell.json', {'cell': NAMES[self.hover] if self.hover is not None else None})
            except OSError:
                pass
        self.handle_actions()
        snap = self.snapshot()
        if snap != self.prev:
            p = self.prev
            if (snap[0], snap[1]) != (p[0], p[1]):
                self.peek = (2, mono + 1.3)
            elif snap[2] != p[2]:
                self.peek = (3, mono + 1.3)
            elif snap[3:5] != p[3:5]:
                self.peek = (0, mono + 1.6)
            elif snap[5:] != p[5:]:
                self.peek = (1, mono + 1.6)
            self.prev = snap
        focus = self.hover if self.hover is not None else (self.peek[0] if mono < self.peek[1] else None)
        for i, spring in enumerate(self.cells):
            if focus is None:
                spring.t = BASE
            else:
                spring.t = EXPAND if i == focus else (INNER - EXPAND) / 3
            spring.step(delta)
        total = sum(sp.x for sp in self.cells) or INNER
        k = INNER / total
        x, pos = PAD, []
        for sp in self.cells:
            w = sp.x * k
            pos.append((x, w))
            x += w
        self.pos = pos
        self.vol_disp.t = 0 if self.sys.muted else self.sys.vol * 100
        self.br_disp.t = self.sys.bright * 100
        self.vol_disp.step(delta)
        self.br_disp.step(delta)
        self.anim += delta
        moving = any(sp.moving for sp in self.cells) or self.vol_disp.moving or self.br_disp.moving \
            or mono < self.peek[1] or self.sys.bt_n > 0 or self.input.get('style') == 'cartoon'
        if moving:
            self.last_activity = mono
        return moving

    # --- drawing -------------------------------------------------------
    def font(self, c, size, bold=False):
        c.select_font_face('Noto Sans CJK SC', cairo.FONT_SLANT_NORMAL,
                           cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size)

    def render(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W * SCALE, H * SCALE)
        c = cairo.Context(surface)
        c.scale(SCALE, SCALE)
        accent = rgba(self.input.get('accent'), 1)
        text = rgba(self.input.get('text'), 1, (.91, .91, .9))
        surf = rgba(self.input.get('surface'), .57, (.1, .1, .12))
        # No body of our own: the bar draws its capsule (same fill/opacity as the other widgets).
        # We only clip to the capsule shape so the focus pill stays inside it.
        r = H / 2
        c.new_sub_path()
        c.arc(r, r, r, math.pi / 2, 3 * math.pi / 2)
        c.arc(W - r, r, r, -math.pi / 2, math.pi / 2)
        c.close_path()
        c.clip()
        s = self.sys
        for i, name in enumerate(NAMES):
            x, w = self.pos[i]
            e = clamp((w - BASE) / (EXPAND - BASE))
            # focus pill
            if e > .01:
                c.new_sub_path()
                rr, ph = 11, 22
                px, py, pw = x + 1.5, (H - ph) / 2, w - 3
                c.arc(px + rr, py + rr, rr, math.pi / 2, 3 * math.pi / 2)
                c.arc(px + pw - rr, py + rr, rr, -math.pi / 2, math.pi / 2)
                c.close_path()
                c.set_source_rgba(accent[0], accent[1], accent[2], .20 * e)
                c.fill()
            cx = lerp(x + w / 2, x + 15, e)
            cy = H / 2 - (1.5 * e if name in ('volume', 'brightness') else 0)
            col = text
            if name == 'volume' and not s.muted:
                col = tuple(lerp(text[i], accent[i], e) for i in range(3)) + (1,)
            if name == 'brightness':
                col = tuple(lerp(text[i], accent[i], e) for i in range(3)) + (1,)
            c.save()
            c.translate(cx, cy)
            if self.input.get('style') == 'cartoon':
                if name == 'bluetooth':
                    cartoon_icons.bluetooth(c, s, self.anim)
                elif name == 'wifi':
                    cartoon_icons.wifi(c, s, self.anim)
                elif name == 'volume':
                    cartoon_icons.volume(c, s, self.anim, 0 if s.muted else clamp(self.vol_disp.x / 100))
                else:
                    cartoon_icons.brightness(c, s, self.anim, clamp(self.br_disp.x / 100))
            elif name == 'bluetooth':
                icon_bluetooth(c, s, col, self.anim)
            elif name == 'wifi':
                icon_wifi(c, s, col, self.anim)
            elif name == 'volume':
                self.marker_x = cx - 1.5 - 6.2
                icon_volume(c, s, col, self.anim, 0 if s.muted else clamp(self.vol_disp.x / 100))
            else:
                icon_brightness(c, s, col, self.anim, clamp(self.br_disp.x / 100))
            c.restore()
            # label
            if e > .25:
                a = clamp((e - .25) / .5)
                c.save()
                c.rectangle(x + 2, 0, w - 4, H)
                c.clip()
                if name == 'volume':
                    label, unit = str(max(0, round(self.vol_disp.x))), '%'
                    if s.muted:
                        label, unit = '静音', ''
                elif name == 'brightness':
                    label, unit = str(max(0, round(self.br_disp.x))), '%'
                elif name == 'wifi':
                    label, unit = ('断开', '') if s.wifi is None else (str(s.wifi), '%')
                else:
                    label, unit = ('关', '') if not s.bt_on else (('已连接', '') if s.bt_n else ('开', ''))
                self.font(c, 12.5, True)
                c.set_source_rgba(text[0], text[1], text[2], a)
                tx = x + 28
                c.move_to(tx, 17.5 - 1.5 * e * (1 if name in ('volume', 'brightness') else 0))
                c.show_text(label)
                if unit:
                    adv = c.text_extents(label).x_advance
                    self.font(c, 8.5, True)
                    c.set_source_rgba(text[0], text[1], text[2], a * .6)
                    c.move_to(tx + adv + 1, 17.5 - 1.5 * e * (1 if name in ('volume', 'brightness') else 0))
                    c.show_text(unit)
                c.restore()
            # level bar
            if e > .3 and name in ('volume', 'brightness'):
                frac = clamp((self.vol_disp.x if name == 'volume' else self.br_disp.x) / 100)
                bx, bw = x + 9, w - 18
                a = clamp((e - .3) / .5)
                c.set_source_rgba(text[0], text[1], text[2], .16 * a)
                c.rectangle(bx, 22.6, bw, 2); c.fill()
                c.set_source_rgba(accent[0], accent[1], accent[2], .95 * a)
                c.rectangle(bx, 22.6, bw * frac, 2); c.fill()
        surface.flush()
        return surface

    def paint(self):
        surface = self.render()
        raw = memoryview(surface.get_data()).cast('B')
        out = bytearray(raw)
        out[0::4] = raw[2::4]
        out[2::4] = raw[0::4]
        self.write_status()
        return W, bytes(out)

    def write_status(self):
        t = time.time()
        if t - self.last_status < .4:
            return
        self.last_status = t
        s = self.sys
        bt = ('已连接 %d 台' % s.bt_n) if s.bt_n else ('已开启' if s.bt_on else '已关闭')
        wifi = (s.ssid or 'Wi-Fi') + ' · %d%%' % s.wifi if s.wifi is not None else '未连接'
        tip = '蓝牙 %s\nWi-Fi %s\n音量 %s\n亮度 %d%%\n滚轮调节 · 左键打开该项面板 · 中键静音 · 右键蓝牙开关' % (
            bt, wifi, '静音' if s.muted else '%d%%' % round(s.vol * 100), round(s.bright * 100))
        state = dict(vol=round(s.vol * 100), muted=s.muted, bright=round(s.bright * 100),
                     bt_on=s.bt_on, bt_n=s.bt_n, bt_names=', '.join(s.bt_names),
                     wifi_on=s.wifi_on, wifi=s.wifi, ssid=s.ssid,
                     device=s.backlight.name if s.backlight else '', max_raw=s.max_raw)
        save_json(STATE / 'status.json', dict(width=W, tooltip=tip, updated=t, state=state, marker=MARK.get('rgb'),
                  marker_x=getattr(self, 'marker_x', None), cells=[[round(x, 1), round(w, 1)] for x, w in self.pos]))


if __name__ == '__main__':
    from stream_server import serve
    serve(Capsule, STATE, 'canvas', W, H, headless=True)

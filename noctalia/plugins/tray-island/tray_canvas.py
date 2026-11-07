#!/usr/bin/env python3
"""Tray island bar capsule: a chevron that turns when the island is open, and the input-method indicator."""
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path.home() / '.config/notifd'))

import cairo  # noqa: E402

from gfx import Spring, clamp  # noqa: E402
from stream_server import serve  # noqa: E402

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'tray-island'
W, H, SCALE = 38, 28, 2
CHEV_X, IME_X = 9.0, 29.0       # same footprint as Noctalia's own tray capsule
IME_NAMES = {'keyboard-us': '英', 'pinyin': '中'}


def read_json(p):
    try:
        v = json.loads(Path(p).read_text())
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def rgb(h, fb):
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (TypeError, ValueError):
        return fb


class Tray:
    def __init__(self):
        STATE.mkdir(parents=True, exist_ok=True)
        self.input, self.input_t, self.alive_t = {}, 0.0, 0.0
        self.is_open = False
        self.turn = Spring(0, omega=22, zeta=.62)
        self.hov = [Spring(0, omega=24, zeta=.8), Spring(0, omega=24, zeta=.8)]
        self.press = [Spring(0, omega=30, zeta=.55), Spring(0, omega=30, zeta=.55)]
        self.ime = '中'
        self.ime_flip = Spring(1, omega=26, zeta=.6)
        self._last_status = 0.0
        self.marker = None
        threading.Thread(target=self._ime_loop, daemon=True).start()

    def _ime_loop(self):
        while True:
            try:
                out = subprocess.check_output(['fcitx5-remote', '-n'], timeout=1.5, stderr=subprocess.DEVNULL).decode().strip()
                label = IME_NAMES.get(out, '中' if out and not out.startswith('keyboard') else '英')
                if label != self.ime:
                    self.ime = label
                    self.ime_flip.x, self.ime_flip.v, self.ime_flip.t = 0.0, 0.0, 1.0
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(.25)

    def step(self, delta, now):
        mono = time.monotonic()
        if mono - self.input_t > .03:
            self.input_t = mono
            self.input = read_json(STATE / 'input.json')
        if mono - self.alive_t > .08:
            self.alive_t = mono
            self.is_open = bool(read_json(STATE / 'island-alive.json').get('open'))
        hx = self.input.get('x') if self.input.get('hovered') else None
        cell = None if hx is None else (0 if hx * W < W / 2 else 1)
        for i in range(2):
            self.hov[i].t = 1.0 if cell == i else 0.0
        cmd = self.input.get('press')
        if cmd and cmd != getattr(self, '_press_seen', None):
            self._press_seen = cmd
            i = 0 if str(cmd).startswith('c') else 1
            self.press[i].x = 1.0
            self.press[i].t = 0.0
        self.turn.t = 1.0 if self.is_open else 0.0
        moving = False
        for sp in [self.turn, self.ime_flip] + self.hov + self.press:
            sp.step(delta)
            moving = moving or not sp.settled
        return moving

    def paint(self):
        text = rgb(self.input.get('text'), (.91, .91, .9))
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W * SCALE, H * SCALE)
        c = cairo.Context(surf)
        c.scale(SCALE, SCALE)
        # hover discs
        for i, cx in enumerate((CHEV_X, IME_X)):
            h = clamp(self.hov[i].x)
            if h > .01:
                c.arc(cx, H / 2, 9.0, 0, math.tau)
                c.set_source_rgba(*text, .12 * h)
                c.fill()
        # dropdown arrow (turns over when the island is open). It is drawn in the marker colour -- the icon colour
        # with two channels off by 1/255, invisible to the eye -- so the island can find this capsule on screen.
        mk = (max(0, round(text[0] * 255) - 1), max(0, round(text[1] * 255) - 1), round(text[2] * 255))
        self.marker = mk
        pr = self.press[0].x
        c.save()
        c.translate(CHEV_X, H / 2 + .2)
        c.rotate(math.pi * self.turn.x)
        s = 1 - .12 * pr
        c.scale(s, s)
        c.set_source_rgb(mk[0] / 255, mk[1] / 255, mk[2] / 255)
        c.set_line_join(1)
        c.set_line_width(1.6)
        c.move_to(-3.4, -1.8)
        c.line_to(3.4, -1.8)
        c.line_to(0, 1.8)
        c.close_path()
        c.fill_preserve()
        c.stroke()
        c.restore()
        # input method
        c.save()
        c.translate(IME_X, H / 2)
        k = clamp(self.ime_flip.x, 0, 1.2)
        c.scale(1, max(.05, k))
        ps = 1 - .1 * self.press[1].x
        c.scale(ps, ps)
        c.select_font_face('Noto Sans CJK SC', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(13)
        ext = c.text_extents(self.ime)
        c.set_source_rgba(*text, 1)
        c.move_to(-ext.width / 2 - ext.x_bearing, -ext.height / 2 - ext.y_bearing)
        c.show_text(self.ime)
        c.restore()
        raw = memoryview(surf.get_data()).cast('B')
        out = bytearray(raw)
        out[0::4] = raw[2::4]
        out[2::4] = raw[0::4]
        t = time.time()
        if t - self._last_status > .5:
            self._last_status = t
            tmp = STATE / 'status.tmp'
            tmp.write_text(json.dumps(dict(updated=t, width=W, marker=list(mk), marker_x=7.4, tooltip='托盘 · 点 ∨ 展开')))
            os.replace(tmp, STATE / 'status.json')
        return W, bytes(out)


if __name__ == '__main__':
    serve(Tray, STATE, 'canvas', W, H, headless=True)

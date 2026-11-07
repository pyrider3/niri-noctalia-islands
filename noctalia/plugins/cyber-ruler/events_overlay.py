#!/usr/bin/env python3
"""Cyber Ruler event overlay: announces mic / Wi-Fi / Bluetooth / DND / lock keys / power profile / layout changes.

Draws nothing while idle; on an event a black pill morphs over the ruler, shows the message, then retracts.
Run: events_overlay.py --state DIR   (reads DIR/input.json: width, height, text, accent)
"""
import sys
import time
from pathlib import Path

import cairo

import events_core as core
from events_core import Hub, clamp, lerp, read_json, rgb, save_json

BLACK = (.016, .016, .022)


class Overlay(Hub):
    def __init__(self):
        super().__init__()
        self.ow, self.oh = 300, 42
        self.life = 0.0
        self._last_input = 0.0

    def poll_events(self, now):
        # only the message events; workspace changes are the ruler's own job
        super().poll_events(now)
        if self.trans and self.trans.get('kind') != 'msg':
            self.trans = None

    def step(self, delta, now):
        v = self.input if isinstance(self.input, dict) else {}
        if v.get('off'):
            import os
            os._exit(0)
        self.ow = int(clamp(float(v.get('width') or 300), 120, 520))
        self.oh = int(clamp(float(v.get('height') or 42), 24, 80))
        moving = super().step(delta, now)
        return moving or bool(self.trans) or self.mix.x > .01

    def render(self):
        mono = time.monotonic()
        text = rgb(self.input.get('text'), (.96, .96, .96))
        accent = rgb(self.input.get('accent'), (.21, .52, .89))
        W, Hh = self.ow, self.oh
        S = core.SCALE
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W * S, Hh * S)
        c = cairo.Context(surf)
        c.scale(S, S)
        mx = clamp(self.mix.x, 0, 1.08)
        tr = self.trans
        if tr and tr.get('label') is not None:
            self._label_w = tr
        if mx < .01:
            return surf
        tr = tr or getattr(self, '_label_w', None)
        if not tr:
            return surf
        m = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        self.font(m, 12, True)
        content_w = 18 + 9 + m.text_extents(tr.get('label', '')).x_advance
        pill_w = float(W)
        pw = lerp(Hh - 8, pill_w, clamp(mx))
        ph = Hh - 8
        px, py = (W - pw) / 2, 4
        a = clamp(mx * 1.4)
        c.push_group()
        self.rr(c, px, py, pw, ph, ph / 2)
        c.set_source_rgb(*BLACK)
        c.fill_preserve()
        c.set_source_rgba(1, 1, 1, .09)
        c.set_line_width(1)
        c.stroke()
        if mx > .55:
            c.save()
            self.rr(c, px, py, pw, ph, ph / 2)
            c.clip()
            c.translate(px + (pw - content_w) / 2 - 11, py + (ph - core.H) / 2)
            c.push_group()
            self.draw_transient(c, int(pw), tr, text, accent)
            c.pop_group_to_source()
            c.paint_with_alpha(clamp((mx - .55) / .35))
            c.restore()
        c.pop_group_to_source()
        c.paint_with_alpha(a)
        return surf

    def paint(self):
        surf = self.render()
        raw = memoryview(surf.get_data()).cast('B')
        out = bytearray(raw)
        out[0::4] = raw[2::4]
        out[2::4] = raw[0::4]
        t = time.time()
        if t - getattr(self, '_st', 0) > .5:
            self._st = t
            save_json(core.STATE / 'status.json', dict(updated=t))
        return self.ow, bytes(out), self.oh


def main():
    args = sys.argv[1:]
    state = Path(args[args.index('--state') + 1])
    state.mkdir(parents=True, exist_ok=True)
    core.STATE = state
    from events_stream import serve
    serve(Overlay, state, 'canvas', 520, 80, headless=False)


if __name__ == '__main__':
    main()

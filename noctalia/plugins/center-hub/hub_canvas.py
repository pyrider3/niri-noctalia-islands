#!/usr/bin/env python3
"""Center hub canvas: niri workspaces + column map; morphs for volume / brightness / track / workspace changes."""
import json
import math
import os
import subprocess
import threading
import time
from pathlib import Path

import cairo

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'center-hub'
STATUS_CAPSULE = Path.home() / '.local/state/status-capsule/status.json'
MEDIA = Path.home() / '.local/state/media-capsule/status.json'
H, SCALE, MAXW = 28, 2, 420
FONT = 'Noto Sans CJK SC'


def read_json(p):
    try:
        v = json.loads(Path(p).read_text())
        return v if isinstance(v, (dict, list)) else {}
    except (OSError, ValueError):
        return {}


def save_json(p, v):
    try:
        tmp = Path(p).with_suffix('.tmp')
        tmp.write_text(json.dumps(v, ensure_ascii=False))
        os.replace(tmp, p)
    except OSError:
        pass


def rgb(h, fb):
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (TypeError, ValueError, IndexError):
        return fb


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


class Spring:
    def __init__(self, x=0.0, omega=24.0, zeta=.7):
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
        if abs(self.x - self.t) < .004 and abs(self.v) < .01:
            self.x, self.v = self.t, 0.0

    @property
    def moving(self):
        return self.x != self.t or self.v != 0.0


class Niri:
    """Keeps workspaces / windows of the bar's output; the event stream only says *when* to look again."""

    def __init__(self):
        self.workspaces = []
        self.windows = []
        self.lock = threading.Lock()
        self.events = []             # transient notifications for the hub: ('ws', idx)
        self.last_focus_ws = None
        self.dirty = True
        threading.Thread(target=self._stream, daemon=True).start()
        threading.Thread(target=self._refresher, daemon=True).start()

    def _query(self, what):
        try:
            return json.loads(subprocess.check_output(['niri', 'msg', '--json', what], timeout=2).decode())
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _refresher(self):
        while True:
            if self.dirty:
                self.dirty = False
                ws, win = self._query('workspaces'), self._query('windows')
                if isinstance(ws, list) and isinstance(win, list):
                    with self.lock:
                        self.workspaces, self.windows = ws, win
                        foc = next((w for w in ws if w.get('is_focused')), None)
                        if foc is not None:
                            if self.last_focus_ws is not None and foc['id'] != self.last_focus_ws:
                                self.events.append(('ws', foc['idx']))
                            self.last_focus_ws = foc['id']
            time.sleep(.06)

    def _stream(self):
        while True:
            try:
                p = subprocess.Popen(['niri', 'msg', '--json', 'event-stream'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for line in p.stdout:
                    if line.startswith('{"Keyboard') or line.startswith('{"Config'):
                        continue
                    self.dirty = True
            except OSError:
                pass
            time.sleep(2)

    def snapshot(self):
        with self.lock:
            return list(self.workspaces), list(self.windows)

    def take_events(self):
        with self.lock:
            ev, self.events = self.events, []
        return ev


class Sensors:
    """The things Noctalia's own pop-ups used to announce, read from the system (polled in a thread)."""

    def __init__(self):
        self.v = {}
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def _run(cmd):
        try:
            return subprocess.check_output(cmd, timeout=2, stderr=subprocess.DEVNULL).decode()
        except (OSError, subprocess.SubprocessError):
            return None

    def _loop(self):
        n = 0
        while True:
            v = {}
            out = self._run(['pactl', 'list', 'short', 'source-outputs'])
            if out is not None:
                v['mic_use'] = bool(out.strip())
            caps = num = None
            for led in sorted(Path('/sys/class/leds').glob('*::capslock')):
                try:
                    caps = bool(int((led / 'brightness').read_text()))
                    break
                except (OSError, ValueError):
                    pass
            for led in sorted(Path('/sys/class/leds').glob('*::numlock')):
                try:
                    num = bool(int((led / 'brightness').read_text()))
                    break
                except (OSError, ValueError):
                    pass
            if caps is not None:
                v['caps'] = caps
            if num is not None:
                v['num'] = num
            if n % 4 == 0:
                out = self._run(['powerprofilesctl', 'get'])
                if out:
                    v['profile'] = out.strip()
                out = self._run(['niri', 'msg', '--json', 'keyboard-layouts'])
                try:
                    kl = json.loads(out or '{}')
                    v['layout'] = kl['names'][kl['current_idx']]
                except (ValueError, KeyError, IndexError, TypeError):
                    pass
            self.v.update(v)
            n += 1
            time.sleep(.4)


class Hub:
    def __init__(self):
        self.niri = Niri()
        self.sensors = Sensors()
        self.width = Spring(120, omega=22, zeta=.8)
        self.mix = Spring(0, omega=20, zeta=.9)       # 0 idle .. 1 transient
        self.dot_w = {}
        self.focus_col = Spring(0, omega=20, zeta=.7)
        self.input = {}
        self.input_t = 0.0
        self.t = 0.0
        self.cw = 120
        self.trans = None            # dict(kind, t0, dur, ...)
        self.prev = {}
        self.prev_t = 0.0
        self.hits = []
        self.tip = ''
        self.last_status = 0.0
        self.last_draw = 0.0
        self.tw_target = 120.0
        self.first = True

    # --------------------------------------------------------------- data
    def poll_events(self, now):
        # Volume / brightness / track changes are already shown by the status and media capsules: not repeated here.
        # Everything else Noctalia used to pop up (mic, Wi-Fi, Bluetooth, DND, lock keys, layout, power) is announced here.
        cur = dict(self.sensors.v)
        sc = read_json(STATUS_CAPSULE)
        st = sc.get('state') if isinstance(sc, dict) else None
        if isinstance(st, dict):
            cur['wifi'] = st.get('wifi_on') is not False
            cur['bt'] = bool(st.get('bt_on'))
        nd = read_json(Path.home() / '.local/state/notifd/state.json')
        if isinstance(nd, dict) and 'dnd' in nd:
            cur['dnd'] = bool(nd['dnd'])
        if not self.first:
            texts = {
                ('mic_use', True): ('mic', '麦克风使用中'), ('mic_use', False): ('mic-off', '麦克风已停止'),
                ('wifi', True): ('wifi', 'Wi-Fi 已开启'), ('wifi', False): ('wifi-off', 'Wi-Fi 已关闭'),
                ('bt', True): ('bt', '蓝牙已开启'), ('bt', False): ('bt-off', '蓝牙已关闭'),
                ('dnd', True): ('dnd', '勿扰已开启'), ('dnd', False): ('bell', '勿扰已关闭'),
                ('caps', True): ('caps', '大写锁定 开'), ('caps', False): ('caps', '大写锁定 关'),
                ('num', True): ('num', '数字锁定 开'), ('num', False): ('num', '数字锁定 关'),
            }
            for k in ('mic_use', 'wifi', 'bt', 'dnd', 'caps', 'num'):
                if k in cur and k in self.prev and cur[k] != self.prev[k]:
                    icon, label = texts[(k, cur[k])]
                    self.trigger('msg', now, icon=icon, label=label)
            if 'profile' in cur and 'profile' in self.prev and cur['profile'] != self.prev['profile']:
                names = {'performance': '性能', 'balanced': '平衡', 'power-saver': '省电'}
                self.trigger('msg', now, icon='bolt', label='电源模式：' + names.get(cur['profile'], cur['profile']))
            if 'layout' in cur and 'layout' in self.prev and cur['layout'] != self.prev['layout']:
                self.trigger('msg', now, icon='kbd', label='键盘布局：' + str(cur['layout']))
        self.prev.update(cur)
        self.first = False
        for kind, idx in self.niri.take_events():
            ws, win = self.niri.snapshot()
            n = sum(1 for w in win if next((x for x in ws if x['id'] == w.get('workspace_id')), {}).get('idx') == idx)
            self.trigger('ws', now, idx=idx, count=n)

    def trigger(self, kind, now, **kw):
        extend = self.trans and self.trans['kind'] == kind and kind in ('vol', 'bright')
        t0 = self.trans['t0'] if extend else now
        self.trans = dict(kind=kind, t0=t0, end=now + (2.4 if kind == 'track' else 1.8), **kw)

    # --------------------------------------------------------------- step
    def step(self, delta, now):
        mono = time.monotonic()
        if mono - self.input_t > .25:
            self.input_t = mono
            v = read_json(STATE / 'input.json')
            self.input = v if isinstance(v, dict) else {}
        self.t += delta
        self.poll_events(mono)
        if self.trans and mono > self.trans['end']:
            self.trans = None
        self.mix.t = 1.0 if self.trans else 0.0
        self.width.t = self.tw_target
        moving = False
        for sp in [self.width, self.mix, self.focus_col] + list(self.dot_w.values()):
            sp.step(delta)
            moving = moving or sp.moving
        self.cw = max(60, min(MAXW, int(math.ceil(self.width.x))))
        if moving or self.trans:
            self.last_draw = mono
            return True
        if mono - self.last_draw > .08:       # idle: ~12 fps for the pulse on urgent workspaces
            self.last_draw = mono
            return True
        return False

    # ------------------------------------------------------------- drawing
    def model(self, now):
        ws, win = self.niri.snapshot()
        out = [w for w in ws]
        out.sort(key=lambda w: w.get('idx', 0))
        foc = next((w for w in out if w.get('is_focused')), out[0] if out else None)
        cols = {}
        focused_id = None
        if foc:
            for w in win:
                if w.get('workspace_id') != foc['id'] or w.get('is_floating'):
                    continue
                pos = (w.get('layout') or {}).get('pos_in_scrolling_layout')
                if not pos:
                    continue
                cols.setdefault(pos[0], []).append(w)
                if w.get('is_focused'):
                    focused_id = w['id']
        return out, foc, cols, focused_id, win

    def render(self):
        mono = time.monotonic()
        text = rgb(self.input.get('text'), (.96, .96, .96))
        accent = rgb(self.input.get('accent'), (.21, .52, .89))
        danger = (1.0, .42, .4)
        ws, foc, cols, focused_id, win = self.model(mono)
        mx = self.mix.x
        hover_x = self.input.get('x') if self.input.get('hovered') else None
        # ---- idle layout (measured first so the width can follow)
        pad = 9.0
        dots_w = 0.0
        for w in ws:
            key = w['id']
            sp = self.dot_w.get(key)
            tgt = 22.0 if w.get('is_focused') else 7.0
            if sp is None:
                sp = self.dot_w[key] = Spring(tgt, omega=24, zeta=.6)
            sp.t = tgt
            dots_w += sp.x + 5
        dots_w = max(0.0, dots_w - 5)
        col_ids = sorted(cols)
        blocks = []
        for ci in col_ids:
            wins = sorted(cols[ci], key=lambda w: (w.get('layout') or {}).get('pos_in_scrolling_layout', [0, 0])[1])
            cw_px = float((wins[0].get('layout') or {}).get('tile_size', [900, 0])[0])
            blocks.append((ci, wins, clamp(cw_px / 70.0, 9, 30)))
        cols_w = sum(b[2] for b in blocks) + 3 * max(0, len(blocks) - 1)
        idle_w = pad + dots_w + (14 + cols_w if blocks else 0) + pad
        idle_w = max(70.0, idle_w)
        # ---- transient layout
        tr = self.trans
        trans_w = 0.0
        if tr:
            if tr['kind'] in ('vol', 'bright'):
                trans_w = 18 + 8 + 84 + 8 + 26 + 2 * pad
            elif tr['kind'] == 'msg':
                m = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
                self.font(m, 12, True)
                trans_w = 18 + 9 + m.text_extents(tr.get('label', '')).x_advance + 2 * pad + 2
            elif tr['kind'] == 'track':
                trans_w = 20 + 8 + 150 + 2 * pad
            else:
                trans_w = 18 + 8 + 100 + 2 * pad
        if self.input.get('style') == 'ruler':
            idle_w = 300.0
        self.tw_target = lerp(idle_w, trans_w, 1.0) if tr else idle_w
        total = self.cw
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, total * SCALE, H * SCALE)
        c = cairo.Context(surf)
        c.scale(SCALE, SCALE)
        self.hits = []
        # idle layer
        if mx < .98:
            c.push_group()
            if self.input.get('style') == 'ruler':
                self.draw_ruler(c, total, ws, cols, focused_id, text, accent, danger, hover_x)
            else:
                self.draw_idle(c, total, ws, blocks, focused_id, text, accent, danger, hover_x, idle_w, pad)
            c.pop_group_to_source()
            c.paint_with_alpha(1 - mx)
        if tr and mx > .02:
            c.push_group()
            self.draw_transient(c, total, tr, text, accent)
            c.pop_group_to_source()
            c.paint_with_alpha(mx)
        # tooltip
        if foc:
            n = sum(len(v) for v in cols.values())
            title = next((w.get('title') for w in win if w.get('id') == focused_id), '') or ''
            self.tip = '工作区 %d · %d 个窗口' % (foc.get('idx', 0), n) + ('\n' + title[:40] if title else '')
        return surf

    def draw_idle(self, c, total, ws, blocks, focused_id, text, accent, danger, hover_x, idle_w, pad):
        c.save()
        # centre the idle content inside the (springy) canvas
        x = max(pad, (total - idle_w) / 2 + pad)
        for w in ws:
            sp = self.dot_w[w['id']]
            focused = w.get('is_focused')
            urgent = w.get('is_urgent')
            wd = max(5.0, sp.x)
            col = danger if urgent else (accent if focused else text)
            a = 1.0 if focused else (.35 + .25 * (.5 + .5 * math.sin(self.t * 6)) if urgent else .38)
            hot = hover_x is not None and x - 3 <= hover_x <= x + wd + 3
            self.rr(c, x, H / 2 - 3, wd, 6, 3)
            c.set_source_rgba(*col, min(1.0, a + (.25 if hot and not focused else 0)))
            c.fill()
            if wd > 14:
                self.font(c, 9, True)
                lab = str(w.get('idx'))
                ext = c.text_extents(lab)
                c.set_source_rgba(0, 0, 0, .0)
            self.hits.append(dict(kind='ws', idx=w.get('idx'), x0=round(x - 3, 1), x1=round(x + wd + 3, 1)))
            x += wd + 5
        x -= 5
        if blocks:
            x += 9
            c.set_source_rgba(*text, .16)
            c.set_line_width(1)
            c.move_to(round(x) + .5, 8)
            c.line_to(round(x) + .5, 20)
            c.stroke()
            x += 9
            for ci, wins, bw in blocks:
                focused = any(w.get('id') == focused_id for w in wins)
                hot = hover_x is not None and x - 1.5 <= hover_x <= x + bw + 1.5
                n = len(wins)
                th = (16 - 2 * (n - 1)) / n
                for k, w in enumerate(wins):
                    isf = w.get('id') == focused_id
                    by = 6 + k * (th + 2)
                    self.rr(c, x, by, bw, th, min(3.0, th / 2))
                    c.set_source_rgba(*(accent if isf else text), 1.0 if isf else (.5 if hot else .28))
                    c.fill()
                self.hits.append(dict(kind='col', idx=ci, x0=round(x - 1.5, 1), x1=round(x + bw + 1.5, 1)))
                x += bw + 3
        c.restore()

    def draw_ruler(self, c, total, ws, cols, focused_id, text, accent, danger, hover_x):
        """Classic look: a tick ruler with the focused window as a tall glowing pill under a marker, the other
        windows as bars either side, workspaces as small circles on top."""
        col_ids = sorted(cols)
        fi = 0
        for i, ci in enumerate(col_ids):
            if any(w.get('id') == focused_id for w in cols[ci]):
                fi = i
        self.focus_col.t = float(fi)
        self.focus_col.z, self.focus_col.o = .6, 18.0
        # ticks
        c.set_line_cap(1)
        x = 8.0
        n = 0
        while x < total - 8:
            tall = n % 5 == 0
            edge = clamp(min(x - 8, total - 8 - x) / 40.0)
            c.set_source_rgba(*text, (.3 if tall else .17) * edge)
            c.set_line_width(1)
            c.move_to(round(x) + .5, H - 2)
            c.line_to(round(x) + .5, H - (7 if tall else 4.5))
            c.stroke()
            x += 7
            n += 1
        spacing = 20.0
        cx0 = total / 2
        for i, ci in enumerate(col_ids):
            wins = sorted(cols[ci], key=lambda w: (w.get('layout') or {}).get('pos_in_scrolling_layout', [0, 0])[1])
            xx = cx0 + (i - self.focus_col.x) * spacing
            if xx < 10 or xx > total - 10:
                continue
            dist = abs(i - self.focus_col.x)
            focused = i == fi
            edge = clamp(min(xx - 10, total - 10 - xx) / 30.0)
            hot = hover_x is not None and abs(hover_x - xx) < spacing / 2
            if focused:
                g = cairo.RadialGradient(xx, 15, 1, xx, 15, 14)
                g.add_color_stop_rgba(0, *accent, .35)
                g.add_color_stop_rgba(1, *accent, 0)
                c.set_source(g)
                c.rectangle(xx - 14, 0, 28, H)
                c.fill()
                self.rr(c, xx - 4, 7, 8, 16, 4)
                c.set_source_rgba(*accent, 1)
                c.fill()
                c.move_to(xx - 4, 2.5)
                c.line_to(xx + 4, 2.5)
                c.line_to(xx, 7)
                c.close_path()
                c.fill()
            else:
                h = 8 + 3 * (len(wins) - 1)
                self.rr(c, xx - 1.8, H - 5 - h, 3.6, h, 1.8)
                c.set_source_rgba(*text, (.62 if hot else .42) * edge * (1 - clamp(dist / 9.0) * .5))
                c.fill()
            self.hits.append(dict(kind='col', idx=ci, x0=round(xx - spacing / 2, 1), x1=round(xx + spacing / 2, 1)))
        # workspaces: circles on the left of the top edge
        x = 12.0
        for w in ws:
            focused = w.get('is_focused')
            urgent = w.get('is_urgent')
            r = 3.4 if focused else 2.4
            col = danger if urgent else (accent if focused else text)
            a = 1.0 if focused else (.35 + .3 * (.5 + .5 * math.sin(self.t * 6)) if urgent else .4)
            c.arc(x, 5.5, r, 0, math.tau)
            c.set_source_rgba(*col, a)
            c.fill()
            self.hits.append(dict(kind='ws', idx=w.get('idx'), x0=round(x - 5, 1), x1=round(x + 5, 1)))
            x += 10

    def draw_transient(self, c, total, tr, text, accent):
        kind = tr['kind']
        age = time.monotonic() - tr['t0']
        pop = clamp(age / .25)
        x = (total - (self.tw_target - 18)) / 2 if False else 11.0
        cy = H / 2
        if kind in ('vol', 'bright'):
            v = clamp((tr.get('value') or 0) / 100.0)
            muted = tr.get('muted')
            if kind == 'vol':
                self.speaker(c, x + 9, cy, 8.5, text, v, muted)
            else:
                self.sun(c, x + 9, cy, 8.5, accent, v)
            bx = x + 26
            self.rr(c, bx, cy - 3, 84, 6, 3)
            c.set_source_rgba(*text, .18)
            c.fill()
            fw = 84 * (0 if muted else v)
            if fw > 0:
                self.rr(c, bx, cy - 3, max(6.0, fw), 6, 3)
                c.set_source_rgba(*accent, 1)
                c.fill()
                c.arc(bx + max(6.0, fw) - 1, cy, 3.4, 0, math.tau)
                c.set_source_rgba(1, 1, 1, 1)
                c.fill()
            self.font(c, 11.5, True)
            lab = '静音' if muted else str(int(round(v * 100)))
            c.set_source_rgba(*text, .95)
            c.move_to(bx + 84 + 9, cy + 4)
            c.show_text(lab)
        elif kind == 'msg':
            self.msg_icon(c, x + 9, cy, tr.get('icon'), text, accent)
            self.font(c, 12, True)
            c.set_source_rgba(*text, .96)
            c.move_to(x + 9 + 9 + 5, cy + 4.2)
            c.show_text(tr.get('label', ''))
        elif kind == 'track':
            c.set_source_rgba(*accent, 1)
            c.set_line_width(1.8)
            c.set_line_cap(1)
            for i in range(3):
                hgt = 4 + 6 * (.5 + .5 * math.sin(self.t * (5 + i * 1.7) + i))
                self.rr(c, x + i * 5.2, cy + 5 - hgt, 3.2, hgt, 1.6)
                c.fill()
            self.font(c, 12, True)
            title = str(tr.get('title', ''))
            artist = str(tr.get('artist', ''))
            label = title + (' · ' + artist if artist else '')
            c.save()
            c.rectangle(x + 22, 0, 150, H)
            c.clip()
            ext = c.text_extents(label)
            off = 0.0
            if ext.x_advance > 150:
                off = ((self.t * 40) % (ext.x_advance - 150 + 40))
            c.set_source_rgba(*text, .95)
            c.move_to(x + 22 - off, cy + 4.2)
            c.show_text(label)
            c.restore()
        else:
            c.set_source_rgba(*accent, 1)
            self.rr(c, x, cy - 5, 14, 10, 3)
            c.fill()
            self.font(c, 12, True)
            c.set_source_rgba(*text, .95)
            c.move_to(x + 22, cy + 4.2)
            c.show_text('工作区 %d' % tr.get('idx', 0) + (' · %d 个窗口' % tr.get('count', 0)))

    # ---- little helpers
    def msg_icon(self, c, cx, cy, name, text, accent):
        c.save()
        c.translate(cx, cy)
        c.set_source_rgba(*accent, 1)
        c.set_line_width(1.5)
        c.set_line_cap(1)
        c.set_line_join(1)
        if name in ('mic', 'mic-off'):
            self.rr(c, -2.6, -6.5, 5.2, 9, 2.6)
            c.fill()
            c.new_path()
            c.arc(0, 0, 5.4, 0, math.pi)
            c.stroke()
            c.move_to(0, 5.4)
            c.line_to(0, 7.6)
            c.stroke()
            if name == 'mic-off':
                c.set_source_rgba(*text, 1)
                c.move_to(-6, -6)
                c.line_to(6, 7)
                c.stroke()
        elif name in ('wifi', 'wifi-off'):
            c.translate(0, 4)
            for i, r in enumerate((3.5, 7, 10.5)):
                c.new_path()
                c.arc(0, 0, r, -2.27, -.87)
                c.stroke()
            c.arc(0, 0, 1.2, 0, math.tau)
            c.fill()
            if name == 'wifi-off':
                c.set_source_rgba(*text, 1)
                c.move_to(-7, -9)
                c.line_to(7, 3)
                c.stroke()
        elif name in ('bt', 'bt-off'):
            c.move_to(-3.6, -3.4)
            c.line_to(3.6, 3.6)
            c.line_to(0, 6.6)
            c.line_to(0, -6.6)
            c.line_to(3.6, -3.6)
            c.line_to(-3.6, 3.4)
            c.stroke()
            if name == 'bt-off':
                c.set_source_rgba(*text, 1)
                c.move_to(-6, -6)
                c.line_to(6, 7)
                c.stroke()
        elif name in ('dnd', 'bell'):
            c.move_to(-5, 4)
            c.curve_to(-3.5, 3, -3, 1, -3, -1.5)
            c.curve_to(-3, -4.5, -1.5, -6, 0, -6)
            c.curve_to(1.5, -6, 3, -4.5, 3, -1.5)
            c.curve_to(3, 1, 3.5, 3, 5, 4)
            c.close_path()
            c.fill()
            if name == 'dnd':
                c.set_source_rgba(*text, 1)
                c.move_to(-6.5, -6.5)
                c.line_to(6.5, 6.5)
                c.stroke()
        elif name == 'caps':
            c.move_to(0, -6)
            c.line_to(5.5, 0)
            c.line_to(2.4, 0)
            c.line_to(2.4, 4.5)
            c.line_to(-2.4, 4.5)
            c.line_to(-2.4, 0)
            c.line_to(-5.5, 0)
            c.close_path()
            c.fill()
        elif name == 'num':
            self.font(c, 11, True)
            c.move_to(-3.2, 4)
            c.show_text('1')
        elif name == 'bolt':
            c.move_to(1.5, -7)
            c.line_to(-4, 1)
            c.line_to(-.5, 1)
            c.line_to(-1.5, 7)
            c.line_to(4, -1.5)
            c.line_to(.5, -1.5)
            c.close_path()
            c.fill()
        else:
            self.rr(c, -7, -4.5, 14, 9, 2.5)
            c.stroke()
            for i in range(4):
                c.arc(-4.5 + i * 3, -1, .7, 0, math.tau)
                c.fill()
            c.move_to(-3.5, 2)
            c.line_to(3.5, 2)
            c.stroke()
        c.restore()
    def font(self, c, size, bold=False):
        c.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size)

    def rr(self, c, x, y, w, h, r):
        r = max(0.0, min(r, w / 2, h / 2))
        c.new_sub_path()
        c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        c.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        c.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        c.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        c.close_path()

    def speaker(self, c, cx, cy, s, col, level, muted):
        c.save()
        c.translate(cx - 1.5, cy)
        c.set_source_rgba(*col, .55 if muted else 1)
        c.move_to(-s * .5, -s * .2)
        c.line_to(-s * .25, -s * .2)
        c.line_to(s * .05, -s * .48)
        c.line_to(s * .05, s * .48)
        c.line_to(-s * .25, s * .2)
        c.line_to(-s * .5, s * .2)
        c.close_path()
        c.fill()
        c.set_line_width(1.4)
        c.set_line_cap(1)
        if muted:
            c.set_source_rgba(*col, .9)
            c.move_to(s * .35, -s * .22)
            c.line_to(s * .85, s * .22)
            c.move_to(s * .85, -s * .22)
            c.line_to(s * .35, s * .22)
            c.stroke()
        else:
            for i, r in enumerate((.32, .6)):
                a = clamp((level - i * .45) / .2)
                c.set_source_rgba(*col, .22 + .78 * a)
                c.new_path()
                c.arc(s * .05, 0, s * r, -.75, .75)
                c.stroke()
        c.restore()

    def sun(self, c, cx, cy, s, col, level):
        c.save()
        c.translate(cx, cy)
        c.set_source_rgba(*col, 1)
        c.arc(0, 0, s * (.24 + .1 * level), 0, math.tau)
        c.fill()
        c.set_line_width(1.4)
        c.set_line_cap(1)
        for i in range(8):
            a = i * math.tau / 8
            r0, r1 = s * (.42 + .05 * level), s * (.55 + .22 * level)
            c.move_to(math.cos(a) * r0, math.sin(a) * r0)
            c.line_to(math.cos(a) * r1, math.sin(a) * r1)
            c.stroke()
        c.restore()

    def paint(self):
        surf = self.render()
        raw = memoryview(surf.get_data()).cast('B')
        out = bytearray(raw)
        out[0::4] = raw[2::4]
        out[2::4] = raw[0::4]
        now = time.time()
        if now - self.last_status > .4 or self.cw != getattr(self, '_last_cw', None):
            self._last_cw = self.cw
            self.last_status = now
            save_json(STATE / 'status.json', dict(updated=now, width=self.cw, hits=self.hits, tooltip=self.tip))
        return self.cw, bytes(out)


if __name__ == '__main__':
    from stream_server import serve
    serve(Hub, STATE, 'canvas', MAXW, H, headless=True)

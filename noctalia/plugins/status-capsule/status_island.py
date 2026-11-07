#!/usr/bin/env python3
"""Status island: Bluetooth / Wi-Fi / volume / brightness in one dynamic island that grows out of the capsule.

Opens on the cell you clicked; the four tabs at the top switch pages and the island morphs to each page's size.
Commands arrive in ~/.local/state/status-capsule/island-cmd.json (written by widget.luau).
"""
import fcntl
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

_LAYER = '/usr/lib/libgtk4-layer-shell.so'
if _LAYER not in os.environ.get('LD_PRELOAD', '') and os.path.exists(_LAYER):
    _env = dict(os.environ, LD_PRELOAD=(_LAYER + ' ' + os.environ.get('LD_PRELOAD', '')).strip())
    _env.setdefault('GSK_RENDERER', 'gl')
    os.execvpe(sys.executable, [sys.executable] + sys.argv, _env)
os.environ.setdefault('GSK_RENDERER', 'gl')

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'clock-island'))
sys.path.insert(0, str(Path.home() / '.config/notifd'))

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

import barpos  # noqa: E402
import gfx  # noqa: E402
from clock_island import dl, ease_back, ctext, live  # noqa: E402
from gfx import THEME, Spring, clamp, lerp, rrect  # noqa: E402

STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'status-capsule'
BLACK = (.012, .012, .018)
CAP_H, CAP_Y = 26.0, 7.0
CANVAS_IN_CAPSULE = 9.3          # the capsule canvas starts this far inside the capsule
WIN_W, WIN_H = 520, 640
PAGES = ('bluetooth', 'wifi', 'volume', 'brightness')
PAGE_W = {'bluetooth': 348.0, 'wifi': 348.0, 'volume': 372.0, 'brightness': 372.0}
TAB_LABEL = {'bluetooth': '蓝牙', 'wifi': 'Wi-Fi', 'volume': '音量', 'brightness': '亮度'}
ROW_H = 52.0
UI = 0.84          # the whole island is drawn at this scale (content is laid out at 1.0)


def read_json(p):
    try:
        v = json.loads(Path(p).read_text())
        return v if isinstance(v, (dict, list)) else {}
    except (OSError, ValueError):
        return {}


def run(cmd, timeout=6, shell=False):
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError):
        return 1, '', ''


def spawn(cmd):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threading.Thread(target=p.wait, daemon=True).start()
    except OSError:
        pass


def notify(title, body):
    spawn(['notify-send', '-a', '状态', '-i', 'dialog-warning', title, body])


# ---------------------------------------------------------------------- icons
def draw_bt_icon(cr, cx, cy, s, col):
    cr.save()
    cr.translate(cx, cy)
    cr.set_source_rgba(*col)
    cr.set_line_width(max(1.4, s * .13))
    cr.set_line_cap(1)
    cr.set_line_join(1)
    cr.move_to(-s * .3, -s * .28)
    cr.line_to(s * .3, s * .3)
    cr.line_to(0, s * .56)
    cr.line_to(0, -s * .56)
    cr.line_to(s * .3, -s * .3)
    cr.line_to(-s * .3, s * .28)
    cr.stroke()
    cr.restore()


def draw_wifi_icon(cr, cx, cy, s, col, level=3):
    cr.save()
    cr.translate(cx, cy + s * .32)
    cr.set_source_rgba(*col)
    cr.set_line_cap(1)
    cr.set_line_width(max(1.4, s * .13))
    for i, r in enumerate((.3, .62, .94)):
        cr.set_source_rgba(*col[:3], col[3] * (1.0 if i < level else .25))
        cr.new_path()
        cr.arc(0, 0, s * r, -math.radians(130), -math.radians(50))
        cr.stroke()
    cr.set_source_rgba(*col)
    cr.arc(0, 0, s * .08, 0, math.tau)
    cr.fill()
    cr.restore()


def draw_vol_icon(cr, cx, cy, s, col, level, muted=False):
    cr.save()
    cr.translate(cx - s * .18, cy)
    cr.set_source_rgba(*col[:3], col[3] * (.55 if muted else 1))
    cr.move_to(-s * .5, -s * .2)
    cr.line_to(-s * .25, -s * .2)
    cr.line_to(s * .05, -s * .48)
    cr.line_to(s * .05, s * .48)
    cr.line_to(-s * .25, s * .2)
    cr.line_to(-s * .5, s * .2)
    cr.close_path()
    cr.fill()
    cr.set_line_width(max(1.3, s * .12))
    cr.set_line_cap(1)
    if muted:
        cr.set_source_rgba(*col[:3], col[3])
        cr.move_to(s * .3, -s * .2)
        cr.line_to(s * .7, s * .2)
        cr.move_to(s * .7, -s * .2)
        cr.line_to(s * .3, s * .2)
        cr.stroke()
    else:
        for i, r in enumerate((.3, .56)):
            a = clamp((level - i * .45) / .2)
            cr.set_source_rgba(*col[:3], col[3] * (.2 + .8 * a))
            cr.new_path()
            cr.arc(s * .05, 0, s * r, -.75, .75)
            cr.stroke()
    cr.restore()


def draw_sun_icon(cr, cx, cy, s, col, level):
    cr.save()
    cr.translate(cx, cy)
    cr.set_source_rgba(*col)
    cr.arc(0, 0, s * (.2 + .08 * level), 0, math.tau)
    cr.fill()
    cr.set_line_width(max(1.3, s * .11))
    cr.set_line_cap(1)
    for i in range(8):
        a = i * math.tau / 8
        r0, r1 = s * (.36 + .04 * level), s * (.46 + .2 * level)
        cr.move_to(math.cos(a) * r0, math.sin(a) * r0)
        cr.line_to(math.cos(a) * r1, math.sin(a) * r1)
        cr.stroke()
    cr.restore()


def draw_mic_icon(cr, cx, cy, s, col, muted=False):
    cr.save()
    cr.translate(cx, cy)
    cr.set_source_rgba(*col[:3], col[3] * (.55 if muted else 1))
    rrect(cr, -s * .17, -s * .5, s * .34, s * .64, s * .17)
    cr.fill()
    cr.set_line_width(max(1.3, s * .1))
    cr.set_line_cap(1)
    cr.new_path()
    cr.arc(0, s * .04, s * .34, 0, math.pi)
    cr.stroke()
    cr.move_to(0, s * .38)
    cr.line_to(0, s * .56)
    cr.stroke()
    if muted:
        cr.set_source_rgba(*col)
        cr.move_to(-s * .4, -s * .4)
        cr.line_to(s * .4, s * .5)
        cr.stroke()
    cr.restore()


def draw_device_icon(cr, cx, cy, s, col, kind):
    cr.save()
    cr.translate(cx, cy)
    cr.set_source_rgba(*col)
    cr.set_line_width(max(1.4, s * .12))
    cr.set_line_cap(1)
    cr.set_line_join(1)
    if kind == 'headphones':
        cr.new_path()
        cr.arc(0, s * .05, s * .4, math.pi, 0)
        cr.stroke()
        for sx in (-1, 1):
            rrect(cr, sx * s * .4 - s * .1, s * .05, s * .2, s * .34, s * .08)
            cr.fill()
    elif kind == 'keyboard':
        rrect(cr, -s * .5, -s * .28, s, s * .56, s * .1)
        cr.stroke()
        for r in range(2):
            for c in range(4):
                cr.arc(-s * .3 + c * s * .2, -s * .08 + r * s * .2, s * .03, 0, math.tau)
                cr.fill()
    elif kind == 'mouse':
        rrect(cr, -s * .26, -s * .46, s * .52, s * .92, s * .26)
        cr.stroke()
        cr.move_to(0, -s * .46)
        cr.line_to(0, -s * .12)
        cr.stroke()
    elif kind == 'gamepad':
        rrect(cr, -s * .5, -s * .26, s, s * .52, s * .22)
        cr.stroke()
        cr.arc(-s * .24, 0, s * .05, 0, math.tau)
        cr.fill()
        cr.arc(s * .2, -s * .06, s * .05, 0, math.tau)
        cr.fill()
        cr.arc(s * .3, s * .08, s * .05, 0, math.tau)
        cr.fill()
    elif kind == 'speaker':
        rrect(cr, -s * .3, -s * .46, s * .6, s * .92, s * .14)
        cr.stroke()
        cr.arc(0, s * .18, s * .12, 0, math.tau)
        cr.stroke()
        cr.arc(0, -s * .2, s * .05, 0, math.tau)
        cr.fill()
    else:
        draw_bt_icon(cr, 0, 0, s * .9, col)
    cr.restore()


def device_kind(name):
    n = (name or '').lower()
    if 'mouse' in n:
        return 'mouse'
    if 'controller' in n or 'gamepad' in n:
        return 'gamepad'
    if 'keyboard' in n or 'qinglong' in n:
        return 'keyboard'
    if any(k in n for k in ('fit', 'buds', 'pods', 'head', 'edifier')):
        return 'headphones'
    if any(k in n for k in ('speaker', 'sound', 'jbl')):
        return 'speaker'
    return 'other'


def sink_kind(name, desc):
    n = (name + ' ' + desc).lower()
    if 'bluez' in n or 'head' in n:
        return 'headphones'
    if 'hdmi' in n or 'display' in n:
        return 'hdmi'
    return 'speaker'


class StatusIsland:
    def __init__(self, app):
        self.app = app
        self.win = self.catcher = None
        self.is_open = False
        self.page = 'wifi'
        self.prev_page = None
        self.page_t0 = 0.0
        self.s = {}
        self.cells = [[4, 36], [40, 36], [76, 36], [112, 36]]
        self.cap_x, self.cap_w = 1475.0, 163.0
        self.marker_cap = None
        self.marker_t = 0.0
        self.locating = False
        self.L = 0.0
        _, self.screen_w, _ = barpos.screen_info()
        self.mic, self.mic_muted = 0.0, False
        self.sinks, self.default_sink = [], ''
        self.bt_list, self.bt_busy, self.scanning = [], {}, False
        self.wifi_list, self.known, self.wifi_busy = [], {}, {}
        self.pw_for = None
        self.hold = {}
        self.last_sent = {}
        self.sx, self.sy = Spring(1500, omega=15, zeta=.7), Spring(CAP_Y, omega=15, zeta=.7)
        self.sw, self.sh = Spring(36, omega=16, zeta=.62), Spring(CAP_H, omega=12.5, zeta=.68)
        self.ca = Spring(0, omega=18, zeta=1.0)
        self.page_f = Spring(1, omega=18, zeta=.9)
        self.tab_x = Spring(2, omega=20, zeta=.75)
        self.tog = {}
        self.disp = {'vol': Spring(0, omega=22, zeta=.7), 'mic': Spring(0, omega=22, zeta=.7),
                     'bright': Spring(0, omega=22, zeta=.7)}
        self.press_pop = {}
        self.t = 0.0
        self.open_t = 0.0
        self.pointer = None
        self.zones = []
        self.local = None
        self.drag = None
        self.press = None
        self.frame_tick = None
        self._fl = None
        self._busy = True
        self.region_key = None
        self.entry_rect = None
        self.lscroll = {'wifi': Spring(0, omega=20, zeta=.95), 'bt': Spring(0, omega=20, zeta=.95)}
        self.ltarget = {'wifi': 0.0, 'bt': 0.0}
        self.scroll_info = {}
        self.view = None
        self.rows_a = 0.0
        self._row_t0 = time.monotonic()
        cmd = read_json(STATE / 'island-cmd.json')
        self.cmd_seq = cmd.get('seq') if isinstance(cmd, dict) else None
        self._hovered_before = False
        self.read_status()
        GLib.timeout_add(100, self._hover_watch)
        GLib.timeout_add(3000, lambda: self.locate() or False)
        GLib.timeout_add(1500, self._prewarm)
        GLib.timeout_add(50, self._poll)
        GLib.timeout_add(1000, self._beat)
        GLib.timeout_add(400, self._read_tick)
        self._beat()

    # ---------------------------------------------------------------- plumbing
    def _beat(self):
        try:
            tmp = STATE / 'island-alive.tmp'
            tmp.write_text(json.dumps(dict(t=time.time(), open=self.is_open)))
            os.replace(tmp, STATE / 'island-alive.json')
        except OSError:
            pass
        return True

    def _poll(self):
        try:
            d = json.loads((STATE / 'island-cmd.json').read_text())
        except (OSError, ValueError):
            return True
        seq = d.get('seq')
        if seq is None or seq == self.cmd_seq:
            return True
        self.cmd_seq = seq
        cmd = d.get('cmd')
        cell = d.get('cell')
        if cmd == 'open':
            if self.is_open and cell in PAGES:
                self.set_page(cell)
            else:
                self.open(cell if cell in PAGES else 'wifi')
        elif cmd == 'toggle':
            if self.is_open:
                self.close()
            else:
                self.open(cell if cell in PAGES else self.page)
        elif cmd == 'close':
            self.close()
        return True

    def _prewarm(self):
        if self.is_open or self.win is not None:
            return False
        self._ensure_windows()
        self.win.present()

        def hush():
            surface = self.win.get_surface()
            if surface is not None:
                surface.set_input_region(cairo.Region())
        GLib.timeout_add(30, lambda: hush() or False)
        GLib.timeout_add(700, lambda: (self.win.set_visible(False) if not self.is_open else None) or False)
        return False

    def read_status(self):
        st = read_json(STATE / 'status.json')
        if not isinstance(st, dict):
            return
        s = st.get('state') or {}
        now = time.monotonic()
        if now > self.hold.get('vol', 0):
            self.s['vol'], self.s['muted'] = s.get('vol', self.s.get('vol', 0)), bool(s.get('muted', False))
        if now > self.hold.get('bright', 0):
            self.s['bright'] = s.get('bright', self.s.get('bright', 100))
        if now > self.hold.get('bt', 0):
            self.s['bt_on'] = bool(s.get('bt_on'))
        if now > self.hold.get('wifi', 0):
            self.s['wifi_on'] = s.get('wifi_on') is not False
        for k in ('bt_n', 'wifi', 'ssid', 'device', 'max_raw'):
            self.s[k] = s.get(k, self.s.get(k))
        if st.get('cells'):
            self.cells = st['cells']
        self.status_raw = st

    def _read_tick(self):
        self.read_status()
        return True

    # ----------------------------------------------------- capsule position
    def locate(self):
        if self.locating:
            return
        self.locating = True

        def work():
            res = None
            try:
                st = read_json(STATE / 'status.json')
                mk = st.get('marker') if isinstance(st, dict) else None
                mx = st.get('marker_x') if isinstance(st, dict) else None
                if mk and mx is not None:
                    r = barpos.find_marker(tuple(int(v) for v in mk), min_run=3)
                    if r:
                        res = r[0] - float(mx) - CANVAS_IN_CAPSULE
            except (OSError, ValueError, TypeError):
                pass
            GLib.idle_add(self._located, res)
        threading.Thread(target=work, daemon=True).start()

    def _located(self, x):
        self.locating = False
        self.marker_t = time.monotonic()
        if x is not None:
            self.marker_cap = x
            self._measure()
            if self.is_open:
                self._start_frames()
        return False

    def _hover_watch(self):
        v = read_json(STATE / 'input.json')
        hov = bool(v.get('hovered')) if isinstance(v, dict) else False
        if hov and not self._hovered_before and time.monotonic() - self.marker_t > 1.5:
            self.locate()
        self._hovered_before = hov
        return True

    def _measure(self):
        if self.marker_cap is not None and time.monotonic() - self.marker_t < 600:
            self.cap_x = self.marker_cap
        else:
            self.cap_x = self.screen_w - 280.0

    def _cell_rect(self, page):
        i = PAGES.index(page)
        x, w = (self.cells[i] if i < len(self.cells) else (4 + 36 * i, 36))
        return self.cap_x + CANVAS_IN_CAPSULE + x, CAP_Y, float(w), CAP_H

    # ------------------------------------------------------------ geometry
    def page_size(self, page=None):
        page = page or self.page
        w = PAGE_W[page]
        if page == 'bluetooth':
            rows = max(1, min(6, len(self.bt_list) + (1 if any(not d['paired'] for d in self.bt_list) else 0)))
            if not self.s.get('bt_on'):
                rows = 0
            h = 128 + (rows * ROW_H if rows else 24) + 18
        elif page == 'wifi':
            rows = max(1, min(6, len(self.wifi_list)))
            if not self.s.get('wifi_on', True):
                rows = 0
            h = 128 + (rows * ROW_H if rows else 24) + (56 if self.pw_for else 0) + 18
        elif page == 'volume':
            rows = max(1, min(5, len(self.sinks)))
            h = 70 + 108 + 30 + rows * ROW_H + 86
        else:
            h = 70 + 108 + 22
        return w, h

    def _target_rect(self):
        if not self.is_open:
            return self._cell_rect(self.page)
        w, h = self.page_size()
        w, h = w * UI, h * UI
        x = max(10.0, min(self.screen_w - w - 12, self.cap_x + self.cap_w - w))
        return x, 4.0, w, h

    # ------------------------------------------------------------ open/close
    def open(self, page):
        if self.is_open:
            return
        self.page = page
        self.prev_page = None
        self.is_open = True
        self.open_t = time.monotonic()
        self._measure()
        r = self._cell_rect(page)
        self.sx.snap(r[0])
        self.sy.snap(r[1])
        self.sw.snap(r[2])
        self.sh.snap(r[3])
        self.ca.snap(0)
        self.tab_x.snap(PAGES.index(page))
        self.page_f.snap(1)
        self.pw_for = None
        for k in self.ltarget:
            self.ltarget[k] = 0.0
            self.lscroll[k].snap(0)
        self._ensure_windows()
        if time.monotonic() - self.marker_t > 20:
            self.locate()
        fx = self._target_rect()[0]
        self.L = max(0.0, min(fx - 40.0, self.screen_w - WIN_W))
        LS.set_margin(self.win, LS.Edge.LEFT, int(self.L))
        THEME.refresh(force=True)
        self.catcher.present()
        self.win.present()
        self.refresh_page(first=True)
        self._start_frames()

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        self.drag = None
        self.pw_for = None
        self._start_frames()

    def set_page(self, page):
        if page == self.page:
            return
        self.prev_page = self.page
        self.page = page
        self.page_f.x, self.page_f.v, self.page_f.t = 0.0, 0.0, 1.0
        self.page_t0 = time.monotonic()
        self._row_t0 = time.monotonic()
        self.pw_for = None
        for k in self.ltarget:
            self.ltarget[k] = 0.0
        self.tab_x.t = float(PAGES.index(page))
        self.refresh_page()
        self._start_frames()

    # ------------------------------------------------------------------- data
    def refresh_page(self, first=False):
        p = self.page
        self._row_t0 = time.monotonic()
        if p == 'bluetooth':
            self.load_bt()
        elif p == 'wifi':
            self.load_known()
            self.load_wifi(False)
            if first:
                self.load_wifi(True)
        elif p == 'volume':
            self.load_sinks()
            self.load_mic()

    def thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def load_bt(self):
        def work():
            def devs(text):
                out = []
                for line in (text or '').splitlines():
                    parts = line.split(' ', 2)
                    if len(parts) == 3 and parts[0] == 'Device':
                        out.append((parts[1], parts[2]))
                return out
            _, paired, _ = run('bluetoothctl devices Paired', shell=True)
            _, conn, _ = run('bluetoothctl devices Connected', shell=True)
            _, allv, _ = run('bluetoothctl devices', shell=True)
            connected = {m for m, _ in devs(conn)}
            pairedl = devs(paired)
            ps = {m for m, _ in pairedl}
            items = [dict(mac=m, name=n, connected=m in connected, paired=True) for m, n in pairedl]
            items.sort(key=lambda d: (not d['connected'], d['name']))
            for m, n in devs(allv):
                if m not in ps and not re.fullmatch(r'([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}', n):
                    items.append(dict(mac=m, name=n, connected=False, paired=False))
            GLib.idle_add(self._set_bt, items)
        self.thread(work)

    def _set_bt(self, items):
        self.bt_list = items
        return False

    def bt_action(self, item):
        mac = item['mac']
        if self.bt_busy.get(mac):
            return
        self.bt_busy[mac] = True

        def work():
            if item['connected']:
                rc, out, err = run(['bluetoothctl', 'disconnect', mac], 15)
                what = '断开蓝牙'
            elif item['paired']:
                rc, out, err = run(['bluetoothctl', 'connect', mac], 20)
                what = '连接蓝牙'
            else:
                rc, out, err = run('bluetoothctl pair %s && bluetoothctl trust %s && bluetoothctl connect %s' % (mac, mac, mac), 40, shell=True)
                what = '配对蓝牙'
            if rc != 0:
                notify(what + '失败', item['name'])
            self.bt_busy.pop(mac, None)
            self.load_bt()
        self.thread(work)

    def scan_bt(self):
        if self.scanning or not self.s.get('bt_on'):
            return
        self.scanning = True

        def work():
            run(['bluetoothctl', '--timeout', '8', 'scan', 'on'], 14)
            self.scanning = False
            self.load_bt()
        self.thread(work)

    def toggle_bt(self):
        on = not self.s.get('bt_on')
        self.s['bt_on'] = on
        self.hold['bt'] = time.monotonic() + 1.2
        self.thread(lambda: (run(['noctalia', 'msg', 'bluetooth-enable' if on else 'bluetooth-disable']), self.load_bt()))

    def load_known(self):
        def work():
            _, out, _ = run(['nmcli', '-t', '-e', 'no', '-f', 'NAME,TYPE', 'connection', 'show'])
            known = {}
            for line in out.splitlines():
                name, _, kind = line.rpartition(':')
                if kind == '802-11-wireless':
                    known[name] = True
            GLib.idle_add(self._set_known, known)
        self.thread(work)

    def _set_known(self, k):
        self.known = k
        return False

    def load_wifi(self, rescan):
        def work():
            rc, out, _ = run(['nmcli', '-t', '-e', 'no', '-f', 'IN-USE,SIGNAL,SECURITY,SSID', 'dev', 'wifi', 'list',
                              '--rescan', 'yes' if rescan else 'no'], 20 if rescan else 6)
            if rc != 0:
                return
            best, order = {}, []
            for line in out.splitlines():
                parts = line.split(':', 3)
                if len(parts) < 4 or not parts[3]:
                    continue
                use, sig, sec, ssid = parts
                item = dict(ssid=ssid, signal=int(sig or 0), secure=sec not in ('', '--'), active=use == '*')
                cur = best.get(ssid)
                if cur is None:
                    best[ssid] = item
                    order.append(ssid)
                elif item['active'] or (not cur['active'] and item['signal'] > cur['signal']):
                    best[ssid] = item
            GLib.idle_add(self._set_wifi, [best[s] for s in order])
        self.thread(work)

    def _set_wifi(self, items):
        self.wifi_list = items
        return False

    def wifi_action(self, item):
        ssid = item['ssid']
        if self.wifi_busy.get(ssid):
            return
        if item['active']:
            cmd, what = ['nmcli', 'connection', 'down', 'id', ssid], '断开 Wi-Fi'
        elif self.known.get(ssid):
            cmd, what = ['nmcli', 'connection', 'up', 'id', ssid], '连接 Wi-Fi'
        elif item['secure']:
            self.pw_for = ssid
            self._focus_entry = True
            return
        else:
            cmd, what = ['nmcli', 'dev', 'wifi', 'connect', ssid], '连接 Wi-Fi'
        self._wifi_run(ssid, cmd, what)

    def _wifi_run(self, ssid, cmd, what):
        self.wifi_busy[ssid] = True

        def work():
            rc, out, err = run(cmd, 30)
            if rc != 0:
                notify(what + '失败', (err or out).strip().splitlines()[0] if (err or out).strip() else ssid)
            self.wifi_busy.pop(ssid, None)
            self.load_wifi(False)
            self.load_known()
        self.thread(work)

    def toggle_wifi(self):
        on = not self.s.get('wifi_on', True)
        self.s['wifi_on'] = on
        self.hold['wifi'] = time.monotonic() + 1.2
        if not on:
            self.wifi_list = []
        self.thread(lambda: (run(['nmcli', 'radio', 'wifi', 'on' if on else 'off']), self.load_wifi(True) if on else None))

    def load_mic(self):
        def work():
            _, out, _ = run(['wpctl', 'get-volume', '@DEFAULT_AUDIO_SOURCE@'])
            try:
                v = float(out.split()[1]) * 100
                GLib.idle_add(self._set_mic, v, '[MUTED]' in out)
            except (IndexError, ValueError):
                pass
        self.thread(work)

    def _set_mic(self, v, muted):
        if time.monotonic() > self.hold.get('mic', 0):
            self.mic, self.mic_muted = v, muted
        return False

    def load_sinks(self):
        def work():
            _, default, _ = run(['pactl', 'get-default-sink'])
            default = default.strip()
            _, out, _ = run(['pactl', '--format=json', 'list', 'sinks'], 4)
            try:
                data = json.loads(out or '[]')
            except ValueError:
                return
            items = []
            for s in data:
                name = s.get('name', '')
                if not name or name.startswith('wbox_'):
                    continue
                ports = s.get('ports') or []
                if ports and all(p.get('availability') == 'not available' for p in ports) and name != default:
                    continue
                items.append(dict(name=name, desc=s.get('description', name)))
            items.sort(key=lambda it: 0 if 'bluez' in it['name'] else 1)
            GLib.idle_add(self._set_sinks, items, default)
        self.thread(work)

    def _set_sinks(self, items, default):
        self.sinks, self.default_sink = items, default
        return False

    # --- slider actions
    def send(self, key, v, final=False):
        now = time.monotonic()
        if not final and now - self.last_sent.get(key, 0) < .04:
            return
        self.last_sent[key] = now
        self.hold[key] = now + .9
        if key == 'vol':
            v = clamp(v, 0, 100)
            self.s['vol'] = v
            if self.s.get('muted') and v > 0:
                self.s['muted'] = False
                spawn(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', '0'])
            spawn(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', '%.3f' % (v / 100)])
        elif key == 'mic':
            v = clamp(v, 0, 100)
            self.mic = v
            if self.mic_muted and v > 0:
                self.mic_muted = False
                spawn(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SOURCE@', '0'])
            spawn(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SOURCE@', '%.3f' % (v / 100)])
        elif key == 'bright':
            v = clamp(v, 1, 100)
            self.s['bright'] = v
            dev = self.s.get('device')
            if dev:
                raw = max(1, round(v / 100 * float(self.s.get('max_raw') or 1)))
                spawn(['busctl', 'call', 'org.freedesktop.login1', '/org/freedesktop/login1/session/auto',
                       'org.freedesktop.login1.Session', 'SetBrightness', 'ssu', 'backlight', dev, str(raw)])

    def toggle_mute(self, which):
        if which == 'vol':
            self.s['muted'] = not self.s.get('muted')
            self.hold['vol'] = time.monotonic() + .9
            spawn(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', '1' if self.s['muted'] else '0'])
        else:
            self.mic_muted = not self.mic_muted
            self.hold['mic'] = time.monotonic() + .9
            spawn(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SOURCE@', '1' if self.mic_muted else '0'])

    def pick_sink(self, i):
        if i < len(self.sinks):
            self.default_sink = self.sinks[i]['name']
            spawn(['pactl', 'set-default-sink', self.default_sink])

    # ----------------------------------------------------------------- windows
    def _ensure_windows(self):
        if self.win is not None:
            return
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('si-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.TOP)
        LS.set_namespace(catcher, 'status-island-catcher')
        for e in (LS.Edge.TOP, LS.Edge.RIGHT, LS.Edge.BOTTOM, LS.Edge.LEFT):
            LS.set_anchor(catcher, e, True)
        LS.set_exclusive_zone(catcher, -1)
        LS.set_keyboard_mode(catcher, LS.KeyboardMode.NONE)
        blank = Gtk.Box()
        blank.set_hexpand(True)
        blank.set_vexpand(True)
        click = Gtk.GestureClick()
        click.connect('pressed', lambda g, n, x, y: self.close())
        blank.add_controller(click)
        catcher.set_child(blank)
        self.catcher = catcher

        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('si-island')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'status-island')
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_keyboard_mode(win, LS.KeyboardMode.ON_DEMAND)
        win.set_default_size(WIN_W, WIN_H)
        da = Gtk.DrawingArea()
        da.set_content_width(WIN_W)
        da.set_content_height(WIN_H)
        da.set_draw_func(self.draw)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        motion.connect('leave', self._on_leave)
        da.add_controller(motion)
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect('drag-begin', self._drag_begin)
        drag.connect('drag-update', self._drag_update)
        drag.connect('drag-end', self._drag_end)
        da.add_controller(drag)
        rclick = Gtk.GestureClick()
        rclick.set_button(3)
        rclick.connect('released', lambda g, n, x, y: self.close())
        da.add_controller(rclick)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self._on_scroll)
        da.add_controller(scroll)
        # password entry (Wi-Fi) floats over the drawing area
        overlay = Gtk.Overlay()
        overlay.set_child(da)
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_placeholder_text('输入密码，回车连接')
        entry.set_halign(Gtk.Align.START)
        entry.set_valign(Gtk.Align.START)
        entry.set_visible(False)
        entry.add_css_class('si-entry')
        entry.connect('activate', self._on_password)
        overlay.add_overlay(entry)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._on_key)
        win.add_controller(keys)
        win.set_child(overlay)
        css = Gtk.CssProvider()
        css.load_from_string("""
            window.si-island, window.si-catcher { background: transparent; }
            entry.si-entry { background: #17181d; color: #f2f2f5; border: 1px solid #3a3d48; border-radius: 14px;
                             padding: 6px 12px; min-height: 22px; font-size: 13px; }
            entry.si-entry:focus { border-color: #3584e4; }
        """)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win, self.da, self.entry = win, da, entry

    # ------------------------------------------------------------------ frames
    def _start_frames(self):
        if self.win is not None and self.frame_tick is None:
            self._fl = None
            self.frame_tick = self.da.add_tick_callback(self._frame)

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        gap = .0155 if self._busy else .033
        if self._fl and now - self._fl < gap:
            return GLib.SOURCE_CONTINUE
        dt_ = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        THEME.refresh()
        self.t += dt_
        tx, ty, tw, th = self._target_rect()
        self.sx.t, self.sy.t, self.sw.t, self.sh.t = tx, ty, tw, th
        closing = not self.is_open
        for sp, (zo, wo) in ((self.sx, (.7, 15.0)), (self.sy, (.7, 15.0)), (self.sw, (.62, 16.0)), (self.sh, (.7, 13.0))):
            sp.z, sp.o = (zo, wo) if not closing else (.9, wo * 1.7)
        cr_ = self._cell_rect(self.page)
        pw = (self.sw.x - cr_[2]) / max(1.0, PAGE_W[self.page] * UI - cr_[2])
        ph = (self.sh.x - CAP_H) / max(1.0, self.page_size()[1] * UI - CAP_H)
        self.ca.t = 1.0 if (self.is_open and min(pw, ph) > .78) else 0.0
        # displayed slider values ease toward the real ones
        self.disp['vol'].t = 0 if self.s.get('muted') else float(self.s.get('vol') or 0)
        self.disp['mic'].t = 0 if self.mic_muted else float(self.mic or 0)
        self.disp['bright'].t = float(self.s.get('bright') or 0)
        for k, sp in self.lscroll.items():
            sp.t = self.ltarget[k]
        busy = False
        for sp in (self.sx, self.sy, self.sw, self.sh, self.ca, self.page_f, self.tab_x) + tuple(self.press_pop.values()) \
                + tuple(self.tog.values()) + tuple(self.disp.values()) + tuple(self.lscroll.values()):
            sp.step(dt_)
            busy = busy or not sp.settled
        self._busy = busy or self.is_open
        self._place_entry()
        self.da.queue_draw()
        self._update_region()
        # keep data fresh while open
        if self.is_open and int(self.t * 10) % 120 == 0 and self.page in ('volume',):
            pass
        if closing and not busy:
            self.win.set_visible(False)
            self.catcher.set_visible(False)
            self.entry.set_visible(False)
            self.frame_tick = None
            self.region_key = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _rect(self):
        return self.sx.x, self.sy.x, max(8.0, self.sw.x), max(8.0, self.sh.x)

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        key = None
        if self.is_open:
            x, y, w, h = self._rect()
            key = (int(x - self.L), int(y), int(w), int(h))
        if key == self.region_key:
            return
        self.region_key = key
        surface.set_input_region(cairo.Region([cairo.RectangleInt(*key)]) if key else cairo.Region())

    def _place_entry(self):
        r = self.entry_rect
        if self.pw_for and r and self.is_open and self.ca.x > .8:
            x, y, w, h = r
            bx, by, _, _ = self._rect()
            self.entry.set_margin_start(int(bx + x * UI - self.L))
            self.entry.set_margin_top(int(by + y * UI))
            self.entry.set_size_request(int(w * UI), int(h * UI))
            if not self.entry.get_visible():
                self.entry.set_text('')
                self.entry.set_visible(True)
                self.entry.grab_focus()
        elif self.entry.get_visible():
            self.entry.set_visible(False)

    # ------------------------------------------------------------------- draw
    def draw(self, area, cr, W, H):
        try:
            self._draw_outer(cr)
        except Exception:
            import traceback
            try:
                (STATE / 'island-error.txt').write_text(traceback.format_exc())
            except OSError:
                pass

    def _draw_outer(self, cr):
        cr.translate(-self.L, 0)
        cell = self._cell_rect(self.page)
        pw = (self.sw.x - cell[2]) / max(1.0, PAGE_W[self.page] * UI - cell[2])
        fa = clamp(pw * 4.0)
        if fa < .01:
            return
        if fa < .995:
            cr.push_group()
            self._draw(cr)
            cr.pop_group_to_source()
            cr.paint_with_alpha(fa)
        else:
            self._draw(cr)

    def _draw(self, cr):
        x, y, w, h = self._rect()
        fh = self.page_size()[1]
        ph = clamp((self.sh.x - CAP_H) / max(1.0, fh * UI - CAP_H))
        rad = lerp(13.0, 30.0, ph)
        sa = clamp(ph * 1.4)
        fw = PAGE_W[self.page]
        if sa > .02:
            cr.save()
            cr.translate(x, y)
            cr.scale(w / fw, h / max(1.0, fh))
            cr.push_group()
            gfx.shadow(cr, 0, 0, fw, fh, 30, 1.5, 10)
            cr.pop_group_to_source()
            cr.paint_with_alpha(sa)
            cr.restore()
        rrect(cr, x, y, w, h, rad)
        cr.set_source_rgb(*BLACK)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, .07)
        cr.set_line_width(1)
        cr.stroke()
        ca = clamp(self.ca.x)
        if ca > .01:
            cr.save()
            rrect(cr, x, y, w, h, rad)
            cr.clip()
            cr.translate(x, y)
            self.zones = []
            self.entry_rect = None
            self.local = None if self.pointer is None else ((self.pointer[0] - x) / UI, (self.pointer[1] - y) / UI)
            cr.scale(UI, UI)
            cr.translate(0, (1 - ca) * 8)
            cr.push_group()
            self._content(cr)
            cr.pop_group_to_source()
            cr.paint_with_alpha(ca)
            cr.restore()

    # --- zones
    def _zone(self, key, shape, *a):
        self.zones.append((key, shape, a))
        p = self.local
        return p is not None and self._inside(shape, a, p)

    @staticmethod
    def _inside(shape, a, p):
        if shape == 'c':
            cx, cy, r = a
            return (p[0] - cx) ** 2 + (p[1] - cy) ** 2 <= r * r
        x, y, w, h = a
        return x <= p[0] <= x + w and y <= p[1] <= y + h

    def _pop(self, key):
        sp = self.press_pop.get(key)
        return 1.0 + (sp.x if sp else 0.0)

    def _press(self, key):
        sp = self.press_pop.get(key)
        if sp is None:
            sp = self.press_pop[key] = Spring(0, omega=26, zeta=.35)
        sp.x, sp.v, sp.t = -.12, 0.0, 0.0

    def _tog(self, key, on):
        sp = self.tog.get(key)
        if sp is None:
            sp = self.tog[key] = Spring(1.0 if on else 0.0, omega=26, zeta=.6)
        sp.t = 1.0 if on else 0.0
        return clamp(sp.x)

    # ---------------------------------------------------------------- content
    def _content(self, cr):
        th = THEME
        txt, acc = th.text, th.accent
        w = PAGE_W[self.page]
        self._tabs(cr, w, txt, acc)
        f = clamp(self.page_f.x)
        draw = {'bluetooth': self._page_bt, 'wifi': self._page_wifi, 'volume': self._page_vol,
                'brightness': self._page_bright}
        if self.prev_page and f < .98:
            keep = self.zones
            cr.push_group()
            draw[self.prev_page](cr, txt, acc, w, readonly=True)
            cr.pop_group_to_source()
            cr.paint_with_alpha(1 - f)
            self.zones = keep
        cr.push_group()
        cr.translate((1 - f) * 18, 0)
        draw[self.page](cr, txt, acc, w)
        cr.pop_group_to_source()
        cr.paint_with_alpha(f if self.prev_page else 1.0)

    def _tabs(self, cr, w, txt, acc):
        x0, y0, tw, h = 16.0, 14.0, w - 32.0, 36.0
        rrect(cr, x0, y0, tw, h, 18)
        cr.set_source_rgba(*txt, .07)
        cr.fill()
        cw = tw / 4
        px = self.tab_x.x
        rrect(cr, x0 + 3 + cw * px, y0 + 3, cw - 6, h - 6, 15)
        cr.set_source_rgba(*acc, .3)
        cr.fill()
        drawers = (lambda c, x, y, s, col: draw_bt_icon(c, x, y, s, col),
                   lambda c, x, y, s, col: draw_wifi_icon(c, x, y, s, col, 3),
                   lambda c, x, y, s, col: draw_vol_icon(c, x, y, s, col, .8, bool(self.s.get('muted'))),
                   lambda c, x, y, s, col: draw_sun_icon(c, x, y, s, col, .6))
        for i, page in enumerate(PAGES):
            hot = self._zone('tab:' + page, 'r', x0 + cw * i, y0, cw, h)
            act = 1 - clamp(abs(i - px))
            col = (*(acc if act > .5 else txt), .55 + .45 * act + (.12 if hot else 0))
            drawers[i](cr, x0 + cw * (i + .5), y0 + h / 2, 17, col)

    # ---- shared widgets
    def _switch(self, cr, key, x, y, on, acc, txt):
        k = self._tog(key, on)
        hot = self._zone(key, 'r', x - 6, y - 6, 58, 36)
        rrect(cr, x, y, 46, 24, 12)
        cr.set_source_rgba(*[lerp(txt[i] * .3, acc[i], k) for i in range(3)], 1)
        cr.fill()
        cr.arc(x + 12 + 22 * k, y + 12, 9.2 + (.8 if hot else 0), 0, math.tau)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.fill()

    def _head(self, cr, w, title, status, y, txt, acc):
        dl(cr, gfx.text_layout(title, 19, True), 22, y, (*txt, 1))
        dl(cr, gfx.text_layout(status, 12), 23, y + 28, (*txt, .55))

    def _row(self, cr, key, x, y, w, h, hot, active, acc, txt, since, idx):
        rev = ease_back((since - .06 - idx * .035) / .34)
        return rev

    def _slider(self, cr, key, y, label, value, icon, acc, txt, since, big=True):
        x0, x1 = 22.0, PAGE_W[self.page] - 22.0
        h = 56.0 if big else 40.0
        v = value / 100.0
        hot = self._zone(key, 'r', x0 - 8, y - 8, x1 - x0 + 16, h + 16)
        dragging = self.drag and self.drag[0] == key
        rev = ease_back((since - .1) / .4)
        cr.save()
        cr.translate((x0 + x1) / 2, y + h / 2)
        cr.scale(max(.01, rev), max(.01, rev))
        cr.translate(-(x0 + x1) / 2, -(y + h / 2))
        rrect(cr, x0, y, x1 - x0, h, h / 2)
        cr.set_source_rgba(*txt, .1)
        cr.fill()
        fw = max(h, (x1 - x0) * v)
        cr.save()
        rrect(cr, x0, y, x1 - x0, h, h / 2)
        cr.clip()
        g = cairo.LinearGradient(x0, 0, x1, 0)
        g.add_color_stop_rgba(0, *[min(1, c_ + .15) for c_ in acc], 1)
        g.add_color_stop_rgba(1, *acc, 1)
        rrect(cr, x0, y, fw, h, h / 2)
        cr.set_source(g)
        cr.fill()
        # soft shine that drifts along the fill
        shine = (self.t * 80) % (fw + 60) - 30
        sg = cairo.LinearGradient(x0 + shine - 24, 0, x0 + shine + 24, 0)
        sg.add_color_stop_rgba(0, 1, 1, 1, 0)
        sg.add_color_stop_rgba(.5, 1, 1, 1, .14)
        sg.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.set_source(sg)
        cr.rectangle(x0, y, fw, h)
        cr.fill()
        cr.restore()
        icon(cr, x0 + h / 2, y + h / 2, h * .42, (1, 1, 1, 1) if v > .08 else (*txt, .85))
        live(cr, '%d' % round(value), 18, True, x1 - 30, y + h / 2, (1, 1, 1, 1) if v > .86 else (*txt, .95))
        kx = x0 + fw - 4
        cr.arc(kx, y + h / 2, 3.2 + (1.6 if (hot or dragging) else 0), 0, math.tau)
        cr.set_source_rgba(1, 1, 1, .95)
        cr.fill()
        cr.restore()
        dl(cr, gfx.text_layout(label, 12, True), x0 + 6, y - 22, (*txt, .6))

    def _list_row(self, cr, key, y, w, title, sub, active, acc, txt, drawer, right, since, idx, enabled=True):
        rev = ease_back((since - .05 - idx * .04) / .34)
        if rev <= .01:
            return
        x0, rh = 16.0, ROW_H - 4
        if self.view is not None and (y + rh < self.view[0] or y > self.view[1]):
            return
        if self.view is not None:
            zt, zb = max(y, self.view[0]), min(y + rh, self.view[1])
            hot = enabled and self._zone(key, 'r', x0, zt, w - 32, max(0.0, zb - zt))
        else:
            hot = enabled and self._zone(key, 'r', x0, y, w - 32, rh)
        cr.save()
        cr.translate(w / 2, y + rh / 2)
        cr.scale(1, max(.01, rev))
        cr.translate(-w / 2, -(y + rh / 2))
        rrect(cr, x0, y, w - 32, rh, 16)
        cr.set_source_rgba(*(acc if active else txt), .22 if active else (.1 if hot else .04))
        cr.fill()
        drawer(cr, x0 + 26, y + rh / 2, 18, (*(acc if active else txt), 1.0 if active else .85))
        dl(cr, gfx.make_layout(title, 14, True, width=w - 150, lines=1), x0 + 52, y + 8, (*txt, 1))
        if sub:
            dl(cr, gfx.make_layout(sub, 11, False, width=w - 150, lines=1), x0 + 52, y + 27, (*(acc if active else txt), .6))
        right(cr, w - 16 - 14, y + rh / 2)
        cr.restore()

    # ---- scrolling list viewport
    def _begin_list(self, cr, w, key, top, content_h, view_h):
        """Clip to the list area and return the current scroll offset (springy, clamped)."""
        limit = max(0.0, content_h - view_h)
        self.scroll_info[key] = (content_h, view_h)
        self.ltarget[key] = clamp(self.ltarget[key], 0.0, limit)
        off = clamp(self.lscroll[key].x, -14.0, limit + 14.0) if limit > 0 else 0.0
        cr.save()
        cr.rectangle(0, top - 4, w, view_h + 8)
        cr.clip()
        self.view = (top, top + view_h)
        return off

    def _end_list(self, cr, w, key, top, view_h, off, txt):
        cr.restore()
        self.view = None
        content_h, _ = self.scroll_info[key]
        if content_h > view_h + 1:
            th = max(26.0, view_h * view_h / content_h)
            ty = top + (view_h - th) * clamp(off / max(1.0, content_h - view_h))
            rrect(cr, w - 9, ty, 3.5, th, 1.75)
            cr.set_source_rgba(*txt, .22)
            cr.fill()

    # ---- bluetooth
    def _page_bt(self, cr, txt, acc, w, readonly=False):
        since = time.monotonic() - self._row_t0
        on = bool(self.s.get('bt_on'))
        n = self.s.get('bt_n') or 0
        self._head(cr, w, '蓝牙', ('已连接 %d 台' % n) if (on and n) else ('未连接设备' if on else '已关闭'), 66, txt, acc)
        self._switch(cr, 'bt:toggle', w - 70, 70, on, acc, txt)
        if on:
            hot = self._zone('bt:scan', 'c', w - 100, 82, 16)
            cr.arc(w - 100, 82, 15, 0, math.tau)
            cr.set_source_rgba(*txt, .16 if hot else .08)
            cr.fill()
            spin = self.t * 6 if self.scanning else 0.0
            cr.save()
            cr.translate(w - 100, 82)
            cr.rotate(spin)
            cr.set_source_rgba(*txt, .9)
            cr.set_line_width(1.6)
            cr.set_line_cap(1)
            cr.new_path()
            cr.arc(0, 0, 6, .6, math.tau - .6)
            cr.stroke()
            cr.restore()
        y = 124.0
        if not on:
            ctext(cr, '蓝牙已关闭', 13, False, w / 2, y + 12, (*txt, .4))
            return
        sawnew = False
        idx = 0
        if not self.bt_list:
            ctext(cr, '没有已配对的设备，点右上角搜索', 12.5, False, w / 2, y + 14, (*txt, .45))
        has_new = any(not d['paired'] for d in self.bt_list)
        n_rows = len(self.bt_list) + (1 if has_new else 0)
        view_h = max(1, min(6, n_rows)) * ROW_H
        content_h = len(self.bt_list) * ROW_H + (22 if has_new else 0)
        top = y
        off = self._begin_list(cr, w, 'bt', top, content_h, view_h)
        y = top - off
        for item in self.bt_list:
            if not item['paired'] and not sawnew:
                sawnew = True
                dl(cr, gfx.text_layout('可配对的新设备', 11), 24, y + 2, (*txt, .45))
                y += 22
            sub = '已连接 · 点击断开' if item['connected'] else ('已配对' if item['paired'] else '点击配对')
            busy = self.bt_busy.get(item['mac'])
            kind = device_kind(item['name'])

            def right(c, rx, ry, item=item, busy=busy):
                if busy:
                    for k in range(3):
                        a = .3 + .7 * (.5 + .5 * math.sin(self.t * 8 - k * 1.1))
                        c.arc(rx - 16 + k * 8, ry, 2.2, 0, math.tau)
                        c.set_source_rgba(*acc, a)
                        c.fill()
                elif item['connected']:
                    c.set_source_rgba(*acc, 1)
                    c.set_line_width(2)
                    c.set_line_cap(1)
                    c.move_to(rx - 6, ry)
                    c.line_to(rx - 2, ry + 4)
                    c.line_to(rx + 6, ry - 4)
                    c.stroke()
            self._list_row(cr, 'bt:' + item['mac'], y, w, item['name'], sub, item['connected'], acc, txt,
                           lambda c, x, yy, s, col, kind=kind: draw_device_icon(c, x, yy, s, col, kind), right, since, idx)
            y += ROW_H
            idx += 1
        self._end_list(cr, w, 'bt', top, view_h, off, txt)

    # ---- wifi
    def _page_wifi(self, cr, txt, acc, w, readonly=False):
        since = time.monotonic() - self._row_t0
        on = self.s.get('wifi_on', True) is not False
        sig, ssid = self.s.get('wifi'), self.s.get('ssid') or ''
        status = '已关闭' if not on else ((('%s · %d%%' % (ssid or '已连接', sig)) if sig is not None else '未连接'))
        self._head(cr, w, 'Wi-Fi', status, 66, txt, acc)
        self._switch(cr, 'wifi:toggle', w - 70, 70, on, acc, txt)
        if on:
            hot = self._zone('wifi:scan', 'c', w - 100, 82, 16)
            cr.arc(w - 100, 82, 15, 0, math.tau)
            cr.set_source_rgba(*txt, .16 if hot else .08)
            cr.fill()
            cr.set_source_rgba(*txt, .9)
            cr.set_line_width(1.6)
            cr.set_line_cap(1)
            cr.new_path()
            cr.arc(w - 100, 82, 6, .6, math.tau - .6)
            cr.stroke()
        y = 124.0
        if not on:
            ctext(cr, 'Wi-Fi 已关闭', 13, False, w / 2, y + 12, (*txt, .4))
            return
        items = sorted(self.wifi_list, key=lambda a: (not a['active'], not self.known.get(a['ssid'], False), -a['signal']))
        if not items:
            ctext(cr, '正在扫描网络…', 12.5, False, w / 2, y + 14, (*txt, .45))
        extra = 56.0 if self.pw_for else 0.0
        view_h = max(1, min(6, len(items))) * ROW_H + extra
        content_h = len(items) * ROW_H + extra
        top = y
        off = self._begin_list(cr, w, 'wifi', top, content_h, view_h)
        y = top - off
        for idx, item in enumerate(items):
            sub = '已连接 · 点击断开' if item['active'] else ('已保存' if self.known.get(item['ssid']) else '')
            busy = self.wifi_busy.get(item['ssid'])
            level = 3 if item['signal'] >= 66 else (2 if item['signal'] >= 36 else 1)

            def right(c, rx, ry, item=item, busy=busy):
                if busy:
                    for k in range(3):
                        a = .3 + .7 * (.5 + .5 * math.sin(self.t * 8 - k * 1.1))
                        c.arc(rx - 16 + k * 8, ry, 2.2, 0, math.tau)
                        c.set_source_rgba(*acc, a)
                        c.fill()
                    return
                if item['secure']:
                    c.set_source_rgba(*txt, .5)
                    rrect(c, rx - 20, ry - 3, 8, 7, 2)
                    c.fill()
                    c.set_line_width(1.3)
                    c.new_path()
                    c.arc(rx - 16, ry - 3, 2.6, math.pi, 0)
                    c.stroke()
                if item['active']:
                    c.set_source_rgba(*acc, 1)
                    c.set_line_width(2)
                    c.set_line_cap(1)
                    c.move_to(rx - 6, ry)
                    c.line_to(rx - 2, ry + 4)
                    c.line_to(rx + 6, ry - 4)
                    c.stroke()
            self._list_row(cr, 'wifi:' + item['ssid'], y, w, item['ssid'], sub, item['active'], acc, txt,
                           lambda c, x, yy, s, col, lv=level: draw_wifi_icon(c, x, yy, s, col, lv), right, since, idx)
            y += ROW_H
            if self.pw_for == item['ssid']:
                self.entry_rect = (22.0, y, w - 44.0 - 40.0, 36.0)
                self._zone('pw:cancel', 'c', w - 38, y + 18, 15)
                cr.arc(w - 38, y + 18, 14, 0, math.tau)
                cr.set_source_rgba(*txt, .1)
                cr.fill()
                cr.set_source_rgba(*txt, .8)
                cr.set_line_width(1.6)
                cr.set_line_cap(1)
                for s_ in (-1, 1):
                    cr.move_to(w - 38 - 4, y + 18 - 4 * s_)
                    cr.line_to(w - 38 + 4, y + 18 + 4 * s_)
                cr.stroke()
                y += 56
        self._end_list(cr, w, 'wifi', top, view_h, off, txt)

    # ---- volume
    def _page_vol(self, cr, txt, acc, w, readonly=False):
        since = time.monotonic() - self._row_t0
        muted = bool(self.s.get('muted'))
        self._head(cr, w, '音量', '静音' if muted else '%d%%' % round(self.disp['vol'].x), 66, txt, acc)
        # speaker icon button doubles as mute toggle
        hotm = self._zone('mute:vol', 'c', w - 36, 82, 18)
        cr.arc(w - 36, 82, 17, 0, math.tau)
        cr.set_source_rgba(*(acc if not muted else txt), .22 if not muted else .1)
        cr.fill()
        draw_vol_icon(cr, w - 36, 82, 18, (*(acc if not muted else txt), 1), clamp(self.disp['vol'].x / 100), muted)
        self._slider(cr, 'vol', 122.0, '', self.disp['vol'].x,
                     lambda c, x, y, s, col: draw_vol_icon(c, x, y, s, col, clamp(self.disp['vol'].x / 100), muted),
                     acc, txt, since)
        y = 196.0
        dl(cr, gfx.text_layout('输出设备', 12, True), 24, y, (*txt, .55))
        y += 24
        rows = self.sinks[:5]
        if not rows:
            ctext(cr, '正在读取输出设备…', 12.5, False, w / 2, y + 14, (*txt, .45))
        for idx, s_ in enumerate(rows):
            active = s_['name'] == self.default_sink
            kind = sink_kind(s_['name'], s_['desc'])
            name = self._nice(s_['desc'])

            def right(c, rx, ry, active=active):
                if active:
                    c.set_source_rgba(*acc, 1)
                    c.set_line_width(2)
                    c.set_line_cap(1)
                    c.move_to(rx - 6, ry)
                    c.line_to(rx - 2, ry + 4)
                    c.line_to(rx + 6, ry - 4)
                    c.stroke()
            self._list_row(cr, 'sink:%d' % idx, y, w, name, '当前输出' if active else '', active, acc, txt,
                           lambda c, x, yy, sz, col, kind=kind: draw_device_icon(c, x, yy, sz, col, 'headphones' if kind == 'headphones' else 'speaker'),
                           right, since, idx)
            y += ROW_H
        y += 6
        mic_muted = self.mic_muted
        hotmic = self._zone('mute:mic', 'c', 34, y + 20, 16)
        cr.arc(34, y + 20, 15, 0, math.tau)
        cr.set_source_rgba(*(acc if not mic_muted else txt), .22 if not mic_muted else .1)
        cr.fill()
        draw_mic_icon(cr, 34, y + 20, 15, (*(acc if not mic_muted else txt), 1), mic_muted)
        self._mini_slider(cr, 'mic', 58.0, w - 70.0, y + 20, self.disp['mic'].x, acc, txt)

    def _mini_slider(self, cr, key, x0, x1, y, value, acc, txt):
        v = clamp(value / 100)
        hot = self._zone(key, 'r', x0 - 6, y - 12, x1 - x0 + 12, 24)
        dragging = self.drag and self.drag[0] == key
        cr.set_line_width(5)
        cr.set_line_cap(1)
        cr.set_source_rgba(*txt, .14)
        cr.move_to(x0, y)
        cr.line_to(x1, y)
        cr.stroke()
        px = x0 + (x1 - x0) * v
        cr.set_source_rgba(*acc, 1)
        cr.move_to(x0, y)
        cr.line_to(px, y)
        cr.stroke()
        cr.arc(px, y, 6 + (2 if (hot or dragging) else 0), 0, math.tau)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.fill()
        live(cr, '%d' % round(value), 11.5, False, x1 + 24, y, (*txt, .55))

    @staticmethod
    def _nice(desc):
        d = desc.replace('Family 17h/19h/1ah HD Audio Controller', '').replace('Analog Stereo', '').strip()
        return d[:28] if d else desc

    # ---- brightness
    def _page_bright(self, cr, txt, acc, w, readonly=False):
        since = time.monotonic() - self._row_t0
        b = self.disp['bright'].x
        self._head(cr, w, '亮度', '%d%%' % round(b), 66, txt, acc)
        draw_sun_icon(cr, w - 36, 82, 24, (*acc, 1), clamp(b / 100))
        self._slider(cr, 'bright', 122.0, '', b, lambda c, x, y, s, col: draw_sun_icon(c, x, y, s, col, clamp(b / 100)),
                     acc, txt, since)

    # ------------------------------------------------------------------ input
    def _on_motion(self, ctl, x, y):
        self.pointer = (x + self.L, y)
        self._start_frames()

    def _on_leave(self, ctl):
        self.pointer = None
        self._start_frames()

    def _local(self, x, y):
        bx, by, _, _ = self._rect()
        return (x + self.L - bx) / UI, (y - by) / UI

    def _hit(self, p):
        for key, shape, a in reversed(self.zones):
            if self._inside(shape, a, p):
                return key
        return None

    SLIDER_RANGE = {'vol': (22.0, -22.0), 'bright': (22.0, -22.0), 'mic': (58.0, -70.0)}

    def _frac(self, key, px):
        a, b = self.SLIDER_RANGE[key]
        w = PAGE_W[self.page]
        x0, x1 = a, (w + b)
        return clamp((px - x0) / max(1.0, x1 - x0))

    def _drag_begin(self, g, x, y):
        p = self._local(x, y)
        key = self._hit(p)
        self.press = (p, key)
        if key in ('vol', 'bright', 'mic'):
            v = self._frac(key, p[0]) * 100
            self.drag = (key, v)
            self.send(key, v)
        self._start_frames()

    def _drag_update(self, g, dx, dy):
        if self.drag and self.press:
            key = self.drag[0]
            v = self._frac(key, self.press[0][0] + dx / UI) * 100
            self.drag = (key, v)
            self.send(key, v)
            self._start_frames()

    def _drag_end(self, g, dx, dy):
        press, self.press = self.press, None
        d, self.drag = self.drag, None
        if press is None:
            return
        if d:
            self.send(d[0], d[1], final=True)
        elif abs(dx) < 8 and abs(dy) < 8 and press[1]:
            self._act(press[1])
        self._start_frames()

    def _act(self, key):
        self._press(key)
        if key.startswith('tab:'):
            self.set_page(key[4:])
        elif key == 'bt:toggle':
            self.toggle_bt()
        elif key == 'bt:scan':
            self.scan_bt()
        elif key.startswith('bt:'):
            mac = key[3:]
            for it in self.bt_list:
                if it['mac'] == mac:
                    self.bt_action(it)
        elif key == 'wifi:toggle':
            self.toggle_wifi()
        elif key == 'wifi:scan':
            self.load_wifi(True)
        elif key.startswith('wifi:'):
            ssid = key[5:]
            for it in self.wifi_list:
                if it['ssid'] == ssid:
                    self.wifi_action(it)
        elif key == 'pw:cancel':
            self.pw_for = None
        elif key.startswith('mute:'):
            self.toggle_mute(key[5:])
        elif key.startswith('sink:'):
            self.pick_sink(int(key[5:]))

    def _on_password(self, entry):
        text = entry.get_text()
        ssid = self.pw_for
        if ssid and text:
            self.pw_for = None
            self._wifi_run(ssid, ['nmcli', 'dev', 'wifi', 'connect', ssid, 'password', text], '连接 Wi-Fi')

    def _on_scroll(self, ctl, dx, dy):
        if not self.is_open or abs(dy) < .01:
            return True
        step = -dy * 3
        key = {'wifi': 'wifi', 'bluetooth': 'bt'}.get(self.page)
        if key:
            info = self.scroll_info.get(key)
            if info:
                limit = max(0.0, info[0] - info[1])
                self.ltarget[key] = clamp(self.ltarget[key] + dy * ROW_H * .9, 0.0, limit)
            self._start_frames()
            return True
        if self.page == 'volume':
            self.send('vol', clamp(float(self.s.get('vol') or 0) + step, 0, 100), final=True)
        elif self.page == 'brightness':
            self.send('bright', clamp(float(self.s.get('bright') or 0) + step, 1, 100), final=True)
        self._start_frames()
        return True

    def _on_key(self, ctl, keyval, keycode, state):
        name = Gdk.keyval_name(keyval)
        if name == 'Escape':
            if self.pw_for:
                self.pw_for = None
            else:
                self.close()
            return True
        if self.pw_for:
            return False
        if name in ('1', '2', '3', '4'):
            self.set_page(PAGES[int(name) - 1])
        elif name == 'Tab':
            self.set_page(PAGES[(PAGES.index(self.page) + 1) % 4])
        elif name in ('Left', 'Right') and self.page in ('volume', 'brightness'):
            d = 3 if name == 'Right' else -3
            key = 'vol' if self.page == 'volume' else 'bright'
            cur = float(self.s.get('vol' if key == 'vol' else 'bright') or 0)
            self.send(key, cur + d, final=True)
        else:
            return False
        self._start_frames()
        return True


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    lock = open(STATE / 'island.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    app = Gtk.Application(application_id='dev.pr.StatusIsland', flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def on_activate(a):
        a.hold()
        holder['island'] = StatusIsland(a)

    app.connect('activate', on_activate)
    app.run([])


if __name__ == '__main__':
    main()

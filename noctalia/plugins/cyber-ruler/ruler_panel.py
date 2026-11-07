#!/usr/bin/env python3
"""Cyber Ruler panel: click the focused pill and a black island grows out of it showing every
workspace and window, with quick actions for the focused window.

Commands arrive in ~/.local/state/cyber-ruler/panel-cmd.json ({"cmd": "toggle"|"open"|"close", "seq": n}),
written by the ruler when the focused pill is clicked.
"""
import json
import math
import os
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

import gfx  # noqa: E402
from clock_island import dl  # noqa: E402
from gfx import THEME, Spring, clamp, lerp, rrect  # noqa: E402

STATE = Path.home() / '.local/state/cyber-ruler'
CMD = STATE / 'panel-cmd.json'
ALIVE = STATE / 'panel-alive.json'

PW = 480.0                 # panel width
TOP = 8.0                  # panel top, overlapping the bar like the other islands
MAXH = 560.0
SHADOW = 36                # transparent margin around the panel inside the window
HEAD_H, FOOT_H = 58.0, 104.0
PILL = (96.0, 22.0)        # size of the pill the island grows out of
BLACK = (.016, .016, .022)


def app_name(app_id):
    app = (app_id or '').lower()
    if not app:
        return 'EMPTY'
    for needle, label in (('kitty', 'TERMINAL'), ('ghostty', 'TERMINAL'), ('foot', 'TERMINAL'), ('codex', 'CODEX'),
                          ('chatgpt', 'CHATGPT'), ('code', 'CODE'), ('cursor', 'CURSOR'), ('firefox', 'FIREFOX'),
                          ('chrome', 'BROWSER'), ('chromium', 'BROWSER'), ('nautilus', 'FILES')):
        if needle in app:
            return label
    return app.rsplit('.', 1)[-1].upper()[:11]


def read_json(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def niri(*args):
    try:
        return subprocess.run(['niri', 'msg', *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


class Panel:
    def __init__(self, app):
        self.app = app
        self.is_open = False
        self.t = 0.0
        self.sw = Spring(PILL[0], omega=17, zeta=.7)
        self.sh = Spring(PILL[1], omega=14, zeta=.72)
        self.sy = Spring(TOP, omega=17, zeta=.74)
        self.ca = Spring(0, omega=18, zeta=1.0)
        self.scroll = Spring(0, omega=20, zeta=.95)
        self.scroll_t = 0.0
        self.hover_sp = {}
        self.press_sp = {}
        self.ws, self.wins = [], []
        self.zones = []
        self.local = None
        self.frame_tick = None
        self._fl = None
        self.cmd_seq = (read_json(CMD) or {}).get('seq')
        self.sw_screen, self.sh_screen = 1755.0, 1097.0
        self.cx = self.sw_screen / 2
        self.content_h = 200.0
        self.rows_view = (0.0, 0.0)
        self.region_key = None
        self._build()
        GLib.timeout_add(90, self._poll_cmd)
        GLib.timeout_add(1000, self._beat)
        self._beat()

    # ---------------------------------------------------------------- setup
    def _build(self):
        css = Gtk.CssProvider()
        css.load_from_string('window.rp-win, window.rp-catcher { background: transparent; }')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        catcher = Gtk.Window(application=self.app)
        catcher.set_decorated(False)
        catcher.add_css_class('rp-catcher')
        LS.init_for_window(catcher)
        LS.set_layer(catcher, LS.Layer.TOP)
        LS.set_namespace(catcher, 'ruler-panel-catcher')
        for e in (LS.Edge.TOP, LS.Edge.RIGHT, LS.Edge.BOTTOM, LS.Edge.LEFT):
            LS.set_anchor(catcher, e, True)
        LS.set_exclusive_zone(catcher, -1)
        LS.set_keyboard_mode(catcher, LS.KeyboardMode.NONE)
        blank = Gtk.Box(hexpand=True, vexpand=True)
        click = Gtk.GestureClick()
        click.connect('pressed', lambda g, n, x, y: self.close())
        blank.add_controller(click)
        catcher.set_child(blank)
        self.catcher = catcher
        win = Gtk.Window(application=self.app)
        win.set_decorated(False)
        win.add_css_class('rp-win')
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_namespace(win, 'ruler-panel')
        LS.set_exclusive_zone(win, -1)
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_keyboard_mode(win, LS.KeyboardMode.ON_DEMAND)
        self.win_w, self.win_h = int(PW + 2 * SHADOW), int(MAXH + TOP + SHADOW)
        win.set_default_size(self.win_w, self.win_h)
        da = Gtk.DrawingArea()
        da.set_content_width(self.win_w)
        da.set_content_height(self.win_h)
        da.set_draw_func(self.draw)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', lambda c, x, y: self._motion(x, y))
        motion.connect('leave', lambda c: self._motion(None, None))
        da.add_controller(motion)
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect('pressed', self._on_press)
        da.add_controller(click)
        rc = Gtk.GestureClick()
        rc.set_button(3)
        rc.connect('pressed', lambda g, n, x, y: self.close())
        da.add_controller(rc)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self._on_scroll)
        da.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._on_key)
        win.add_controller(keys)
        win.set_child(da)
        self.win, self.da = win, da

    def _beat(self):
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            tmp = ALIVE.with_suffix('.tmp')
            tmp.write_text(json.dumps({'t': time.time(), 'open': self.is_open}))
            os.replace(tmp, ALIVE)
        except OSError:
            pass
        return True

    def _poll_cmd(self):
        d = read_json(CMD)
        if isinstance(d, dict) and d.get('seq') is not None and d['seq'] != self.cmd_seq:
            self.cmd_seq = d['seq']
            cmd = d.get('cmd', 'toggle')
            if cmd == 'close' or (cmd == 'toggle' and self.is_open):
                self.close()
            else:
                self.open()
        return True

    # --------------------------------------------------------------- open/close
    def _measure(self):
        out = niri('--json', 'focused-output')
        try:
            lg = json.loads(out)['logical']
            self.sw_screen, self.sh_screen = float(lg['width']), float(lg['height'])
        except (ValueError, KeyError, TypeError):
            pass
        self.cx = self.sw_screen / 2

    def open(self):
        if self.is_open:
            return
        self._measure()
        # niri reports no focused window once this panel holds keyboard focus: ask before presenting
        self.last_focus = None
        try:
            f = next((x for x in json.loads(niri('--json', 'windows') or '[]') if x.get('is_focused')), None)
            self.last_focus = f['id'] if f else None
        except ValueError:
            pass
        self.is_open = True
        self.open_t = time.monotonic()
        self.sw.snap(PILL[0])
        self.sh.snap(PILL[1])
        self.sy.snap(TOP)
        self.ca.snap(0)
        self.scroll.snap(0)
        self.scroll_t = 0.0
        self.refresh()
        GLib.timeout_add(700, self._refresh_loop)
        LS.set_margin(self.win, LS.Edge.LEFT, int(self.cx - self.win_w / 2))
        LS.set_margin(self.win, LS.Edge.TOP, 0)
        THEME.refresh(force=True)
        self.catcher.set_visible(True)
        self.catcher.present()
        self.win.present()
        self.start_frames()

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        self.start_frames()

    # --------------------------------------------------------------------- data
    def refresh(self):
        def work():
            try:
                ws = json.loads(niri('--json', 'workspaces') or '[]')
                wins = json.loads(niri('--json', 'windows') or '[]')
            except ValueError:
                return
            GLib.idle_add(self._set_model, ws, wins)
        threading.Thread(target=work, daemon=True).start()

    def _set_model(self, ws, wins):
        self.ws, self.wins = ws, wins
        f = next((x for x in wins if x.get('is_focused')), None)
        if f:
            self.last_focus = f['id']
        elif getattr(self, 'last_focus', None) not in {x['id'] for x in wins}:
            self.last_focus = None
        self.start_frames()
        return False

    def _refresh_loop(self):
        if self.is_open:
            self.refresh()
        return self.is_open

    def rows(self):
        """[(workspace, [windows in column order])] sorted like the ruler, floating windows last."""
        out = []
        for w in sorted(self.ws, key=lambda w: (w.get('output', ''), w.get('idx', 0))):
            mine = [x for x in self.wins if x.get('workspace_id') == w['id']]

            def key(x):
                pos = (x.get('layout') or {}).get('pos_in_scrolling_layout') or [9999, 0]
                return (1 if x.get('is_floating') else 0, pos[0], pos[1], x['id'])
            out.append((w, sorted(mine, key=key)))
        return out

    def focused(self):
        f = next((x for x in self.wins if x.get('is_focused')), None)
        if f:
            return f
        lf = getattr(self, 'last_focus', None)
        return next((x for x in self.wins if x['id'] == lf), None)

    # ------------------------------------------------------------------- frames
    def start_frames(self):
        if self.frame_tick is None:
            self._fl = None
            self.frame_tick = self.da.add_tick_callback(self._frame)

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        if self._fl and now - self._fl < .0155:
            return GLib.SOURCE_CONTINUE
        dt = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        self.t += dt
        THEME.refresh()
        opening = self.is_open
        total_h = self.content_h
        target_h = min(MAXH, total_h)
        if opening:
            self.sw.t, self.sh.t, self.sy.t = PW, target_h, TOP
            self.sw.z, self.sw.o = .7, 17.0
            self.sh.z, self.sh.o = .72, 14.0
        else:
            self.sw.t, self.sh.t, self.sy.t = PILL[0], PILL[1], TOP
            self.sw.z, self.sw.o = 1.0, 30.0
            self.sh.z, self.sh.o = 1.0, 30.0
        self.ca.t = 1.0 if (opening and self.sh.x > min(target_h, 120) * .8 and self.sw.x > PW * .8) else 0.0
        limit = max(0.0, total_h - target_h)
        self.scroll_t = clamp(self.scroll_t, 0.0, limit)
        self.scroll.t = self.scroll_t
        busy = False
        for sp in [self.sw, self.sh, self.sy, self.ca, self.scroll] + list(self.hover_sp.values()) + list(self.press_sp.values()):
            sp.step(dt)
            busy = busy or not sp.settled
        self._update_region()
        self.da.queue_draw()
        if not opening and self.sw.x <= PILL[0] + 4:
            self.win.set_visible(False)
            self.catcher.set_visible(False)
            self.region_key = None
            self.frame_tick = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _rect(self):
        w, h = max(8.0, self.sw.x), max(8.0, self.sh.x)
        x = SHADOW + (PW - w) / 2
        return x, self.sy.x, w, h

    def _update_region(self):
        surface = self.win.get_surface()
        if surface is None:
            return
        key = None
        if self.is_open or self.sw.x > PILL[0] + 2:
            x, y, w, h = self._rect()
            key = (int(x), int(y), int(w), int(h))
        if key == self.region_key:
            return
        self.region_key = key
        surface.set_input_region(cairo.Region([cairo.RectangleInt(*key)]) if key else cairo.Region())

    # ------------------------------------------------------------------ drawing
    def draw(self, area, cr, W, H):
        try:
            self._draw(cr)
        except Exception:
            import traceback
            try:
                (STATE / 'panel-error.txt').write_text(traceback.format_exc())
            except OSError:
                pass

    def _hot(self, key, x, y, w, h):
        self.zones.append((key, x, y, w, h))
        p = self.local
        return p is not None and x <= p[0] <= x + w and y <= p[1] <= y + h

    def _sp(self, store, key, omega=22, zeta=.7):
        sp = store.get(key)
        if sp is None:
            sp = store[key] = Spring(0, omega=omega, zeta=zeta)
        return sp

    def _draw(self, cr):
        # while closing, fade out as the island shrinks back to the pill so no empty black stub lingers
        ga = 1.0 if self.is_open else clamp((self.sw.x - PILL[0]) / 70.0)
        if ga < .01:
            return
        if ga >= .999:
            return self._draw_body(cr)
        cr.push_group()
        self._draw_body(cr)
        cr.pop_group_to_source()
        cr.paint_with_alpha(ga)

    def _draw_body(self, cr):
        x, y, w, h = self._rect()
        txt, acc = THEME.text, THEME.accent
        self.zones = []
        gfx.shadow(cr, x, y, w, h, 28, 1.5, 10)
        rrect(cr, x, y, w, h, min(28, h / 2))
        cr.set_source_rgb(*BLACK)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, .09)
        cr.set_line_width(1)
        cr.stroke()
        a = clamp(self.ca.x)
        if a < .02:
            return
        cr.save()
        rrect(cr, x, y, w, h, min(28, h / 2))
        cr.clip()
        cr.translate(x, y)
        cr.push_group()
        self._content(cr, w, h, txt, acc, x, y)
        cr.pop_group_to_source()
        cr.paint_with_alpha(a)
        cr.restore()

    def _content(self, cr, w, h, txt, acc, ox, oy):
        # pointer in panel coordinates
        p = self.local
        if p is not None:
            self.local_p = (p[0] - ox, p[1] - oy)
        else:
            self.local_p = None
        saved = self.local
        self.local = self.local_p
        rows = self.rows()
        foc = self.focused()
        n_win = len(self.wins)
        fw0 = self.focused()
        cur = next((r for r in rows if (fw0.get('workspace_id') == r[0]['id'] if fw0 else r[0].get('is_focused'))), None)
        # ---- header
        title = '工作区 %02d' % (cur[0].get('idx', 0) if cur else 0)
        dl(cr, gfx.text_layout(title, 17, True), 22, 18, (*txt, 1))
        sub = '%d 个工作区 · %d 个窗口' % (len(rows), n_win)
        lay = gfx.text_layout(sub, 12)
        dl(cr, lay, w - 22 - gfx.text_size(lay)[0], 24, (*txt, .5))
        # ---- rows (scrollable)
        top, bottom = HEAD_H, h - FOOT_H
        self.rows_view = (top, bottom)
        cr.save()
        cr.rectangle(0, top, w, max(0.0, bottom - top))
        cr.clip()
        off = self.scroll.x
        y = top - off
        inner_w = w - 32
        label_w = 52.0
        for ws, wins in rows:
            lines = self._flow(wins, inner_w - label_w - 12)
            row_h = max(48.0, 14 + len(lines) * 34)
            fw_ = self.focused()
            active = bool(fw_.get('workspace_id') == ws['id']) if fw_ else bool(ws.get('is_focused'))
            if y + row_h >= top and y <= bottom:
                hot_row = self._hot('ws:%d' % ws['idx'], 16, max(y, top), inner_w, min(row_h, bottom - max(y, top)))
                rrect(cr, 16, y, inner_w, row_h - 6, 16)
                cr.set_source_rgba(*(acc if active else txt), .14 if active else (.08 if hot_row else .035))
                cr.fill()
                dl(cr, gfx.text_layout('%02d' % ws.get('idx', 0), 15, True), 30, y + (row_h - 6) / 2 - 10,
                   (*(acc if active else txt), 1 if active else .7))
                if not wins:
                    dl(cr, gfx.text_layout('空', 12), 16 + label_w + 12, y + (row_h - 6) / 2 - 8, (*txt, .35))
                for li, line in enumerate(lines):
                    for (win, cx_, cw_) in line:
                        self._chip(cr, win, 16 + label_w + 12 + cx_, y + 8 + li * 34, cw_, 28, txt, acc, top, bottom)
            y += row_h
        self.content_h = HEAD_H + (y + off - top) + FOOT_H
        cr.restore()
        # scrollbar
        view = bottom - top
        total = self.content_h - HEAD_H - FOOT_H
        if total > view + 1:
            th = max(26.0, view * view / total)
            ty = top + (view - th) * clamp(off / max(1.0, total - view))
            rrect(cr, w - 8, ty, 3.5, th, 1.75)
            cr.set_source_rgba(*txt, .22)
            cr.fill()
        # ---- footer actions for the focused window
        fy = h - FOOT_H
        cr.set_source_rgba(*txt, .07)
        cr.rectangle(16, fy, w - 32, 1)
        cr.fill()
        if foc:
            name = '%s · %s' % (app_name(foc.get('app_id')), (foc.get('title') or '')[:48])
        else:
            name = '没有聚焦的窗口'
        dl(cr, gfx.make_layout(name, 12.5, True, width=w - 44, lines=1), 22, fy + 14, (*txt, .85 if foc else .4))
        floating = bool(foc and foc.get('is_floating'))
        acts = [('float', '平铺' if floating else '浮动', False), ('full', '全屏', False), ('up', '↑ 工作区', False),
                ('down', '↓ 工作区', False), ('close', '关闭', True)]
        bw, gap = (inner_w - 4 * 8) / 5, 8.0
        for i, (key, label, danger) in enumerate(acts):
            bx, by = 16 + i * (bw + gap), fy + 46
            enabled = foc is not None
            hot = enabled and self._hot('act:' + key, bx, by, bw, 40)
            sp = self._sp(self.hover_sp, 'a' + key)
            sp.t = 1.0 if hot else 0.0
            ps = self._sp(self.press_sp, 'p' + key, 26, .6)
            sc = 1 - .05 * ps.x
            cr.save()
            cr.translate(bx + bw / 2, by + 20)
            cr.scale(sc, sc)
            cr.translate(-bw / 2, -20)
            rrect(cr, 0, 0, bw, 40, 14)
            base = (1.0, .42, .4) if danger else txt
            cr.set_source_rgba(*base, (.07 + .1 * sp.x) if enabled else .03)
            cr.fill()
            lay = gfx.text_layout(label, 12.5, True)
            lw, lh = gfx.text_size(lay)
            dl(cr, lay, (bw - lw) / 2, (40 - lh) / 2, (*(base if danger else txt), (.95 if enabled else .3)))
            cr.restore()
        self.local = saved

    def _flow(self, wins, width):
        """Lay the windows out in lines of chips; columns are separated by a slightly wider gap."""
        lines, line, x = [], [], 0.0
        last_col = None
        for win in wins:
            label = app_name(win.get('app_id'))
            lay = gfx.text_layout(label, 12.5, True)
            cw = gfx.text_size(lay)[0] + 30 + (10 if win.get('is_urgent') else 0)
            col = ((win.get('layout') or {}).get('pos_in_scrolling_layout') or [None])[0] if not win.get('is_floating') else 'f'
            gap = 0.0 if not line else (5.0 if col == last_col else 10.0)
            if line and x + gap + cw > width:
                lines.append(line)
                line, x, gap = [], 0.0, 0.0
            line.append((win, x + gap, cw))
            x += gap + cw
            last_col = col
        if line:
            lines.append(line)
        return lines

    def _chip(self, cr, win, x, y, w, h, txt, acc, top, bottom):
        fw = self.focused()
        focused = bool(fw and fw['id'] == win['id'])
        vis_top, vis_bot = max(y, top), min(y + h, bottom)
        hot = vis_bot > vis_top and self._hot('win:%d' % win['id'], x, vis_top, w, vis_bot - vis_top)
        sp = self._sp(self.hover_sp, 'w%d' % win['id'])
        sp.t = 1.0 if hot else 0.0
        rrect(cr, x, y, w, h, 14)
        if focused:
            cr.set_source_rgba(*acc, .34)
        else:
            cr.set_source_rgba(*txt, .07 + .09 * sp.x)
        cr.fill()
        if focused:
            rrect(cr, x + .5, y + .5, w - 1, h - 1, 13.5)
            cr.set_source_rgba(*acc, .8)
            cr.set_line_width(1)
            cr.stroke()
        elif win.get('is_floating'):
            rrect(cr, x + .5, y + .5, w - 1, h - 1, 13.5)
            cr.set_source_rgba(*txt, .3)
            cr.set_line_width(1)
            cr.set_dash([3, 3])
            cr.stroke()
            cr.set_dash([])
        # small dot: accent when focused, orange when urgent
        dot = (1.0, .55, .36) if win.get('is_urgent') else (acc if focused else txt)
        cr.arc(x + 13, y + h / 2, 3 if focused or win.get('is_urgent') else 2.4, 0, math.tau)
        cr.set_source_rgba(*dot, 1 if (focused or win.get('is_urgent')) else .45)
        cr.fill()
        lay = gfx.text_layout(app_name(win.get('app_id')), 12.5, True)
        lw, lh = gfx.text_size(lay)
        dl(cr, lay, x + 23, y + (h - lh) / 2, (*txt, 1 if focused else .85))

    # -------------------------------------------------------------------- input
    def _motion(self, x, y):
        self.local = None if x is None else (x, y)
        self.start_frames()

    def _on_press(self, g, n, x, y):
        if not self.is_open:
            return
        # zones were recorded in panel coordinates (origin at the rect's top-left)
        rx, ry, _, _ = self._rect()
        px, py = x - rx, y - ry
        for key, zx, zy, zw, zh in reversed(self.zones):
            if zx <= px <= zx + zw and zy <= py <= zy + zh:
                self._act(key)
                break
        self.start_frames()

    def _act(self, key):
        foc = self.focused()
        if key.startswith('win:'):
            wid = key[4:]
            self._run(['action', 'focus-window', '--id', wid])
            GLib.timeout_add(160, lambda: self.close() or False)
        elif key.startswith('ws:'):
            self._run(['action', 'focus-workspace', key[3:]])
            GLib.timeout_add(160, lambda: self.close() or False)
        elif key.startswith('act:') and foc:
            what, wid = key[4:], str(foc['id'])
            self._press_anim(what)
            if what == 'float':
                self._run(['action', 'toggle-window-floating', '--id', wid])
            elif what == 'full':
                self._run(['action', 'fullscreen-window', '--id', wid])
                GLib.timeout_add(200, lambda: self.close() or False)
            elif what in ('up', 'down'):
                cur = next((w for w in self.ws if w['id'] == foc.get('workspace_id')), None)
                if cur:
                    idx = cur.get('idx', 1) + (-1 if what == 'up' else 1)
                    same = [w.get('idx') for w in self.ws if w.get('output') == cur.get('output')]
                    if idx in same or idx == max(same, default=0) + 1:
                        self._run(['action', 'move-window-to-workspace', '--window-id', wid, str(idx)])
            elif what == 'close':
                self._run(['action', 'close-window', '--id', wid])

    def _press_anim(self, what):
        sp = self._sp(self.press_sp, 'p' + what, 26, .6)
        sp.x = 1.0
        sp.t = 0.0

    def _run(self, args):
        def work():
            niri(*args)
            time.sleep(.12)
            GLib.idle_add(self.refresh)
        threading.Thread(target=work, daemon=True).start()

    def _on_scroll(self, ctl, dx, dy):
        if self.is_open:
            self.scroll_t += dy * 60
            self.start_frames()
        return True

    def _on_key(self, ctl, keyval, keycode, state):
        if Gdk.keyval_name(keyval) == 'Escape':
            self.close()
            return True
        return False


def main():
    app = Gtk.Application(application_id='dev.pr.RulerPanel', flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def on_activate(a):
        if holder.get('p') is None:
            a.hold()
            holder['p'] = Panel(a)

    app.connect('activate', on_activate)
    app.run([])


if __name__ == '__main__':
    main()

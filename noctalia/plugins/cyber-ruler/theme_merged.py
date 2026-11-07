"""Merged theme: every workspace and every window on ONE tape.

Workspaces are groups separated by hairlines. The active group is expanded into capsules, the
others stay compact; the focused window swells into a labelled accent pill. The tape scrolls with
spring motion so the focused window always rests under the fixed index.
"""
import math, cairo
from heading_spring import HeadingTheme as SpringHeadingTheme, KineticMotion, Motion
import json, os, time
from pathlib import Path
from island_feed import Feed
from events_core import Spring as EvSpring
from theme_kit import DEFAULT, WHITE, GRAY, ORANGE, mix, smooth, fill_capsule, capsule, glow, soft_glow, label, text_width

SMALL, FULL = 4., 7.          # capsule width of a window in an inactive / active workspace
GAP, GROUP_GAP = 3.5, 11.

class MergedTheme(SpringHeadingTheme):
    LABEL_SIZE = 7.5
    def __init__(self):
        super().__init__()
        self.focus = KineticMotion(); self.expand = {}; self.items = []; self.item_x = []
        self.focus_index = 0; self.total = 0
        self.feed = None; self.ev = 0.; self.ev_v = 0.; self.ev_t = None; self.ev_msg = None
        self.ev_prev = None; self.ev_xf = EvSpring(1.0, omega=24, zeta=.9); self.ev_wsp = None
    def accent_color(self, ruler):
        return ruler.accent_rgb(DEFAULT)

    # ---- model -------------------------------------------------------------------------------
    def build_items(self, ruler):
        items = []
        for wi, ws in enumerate(ruler.workspaces):
            columns = ws.get('columns', [])
            if not columns:
                items.append(dict(ws=ws['id'], wi=wi, column=None, window=None, app='', floating=False, urgent=False, members=0))
            for ci, col in enumerate(columns):
                members = col['windows']; focused = ws.get('focused_window')
                member = next((m for m in members if m['id'] == focused), members[0])
                items.append(dict(ws=ws['id'], wi=wi, column=ci, window=member['id'], app=member.get('app', ''), floating=bool(col.get('floating')),
                                  urgent=any(m.get('urgent') for m in members), members=len(members),
                                  focused=ws['id'] == ruler.active_id and any(m['id'] == focused for m in members)))
        return items

    def update(self, ruler, now):
        super().update(ruler, now)
        self.step_event(ruler, now)
        self.items = self.build_items(ruler)
        active = next((k for k, it in enumerate(self.items) if it['ws'] == ruler.active_id and it.get('focused')), None)
        if active is None:
            active = next((k for k, it in enumerate(self.items) if it['ws'] == ruler.active_id), 0)
        self.focus_index = active
        self.focus.move(active, now, ruler.duration, ruler.animate)
        live = {ws['id'] for ws in ruler.workspaces}
        for wid in list(self.expand):
            if wid not in live: del self.expand[wid]
        for wid in live:
            m = self.expand.setdefault(wid, Motion())
            if not m.ready: m.move(1. if wid == ruler.active_id else 0., now, ruler.duration, False)
            else: m.move(1. if wid == ruler.active_id else 0., now, ruler.duration, ruler.animate)

    def step_event(self, ruler, now):
        on = bool(getattr(ruler, 'events', False))
        if on and self.feed is None:
            self.feed = Feed()
        tr = self.feed.poll() if (on and self.feed) else None
        if tr:
            if tr is not self.ev_msg:
                # a new message while the island is showing one: morph between them instead of swapping
                if self.ev_msg is not None and self.ev > .25:
                    self.ev_prev = self.ev_msg
                    self.ev_xf.x, self.ev_xf.v, self.ev_xf.t = 0.0, 0.0, 1.0
                else:
                    self.ev_prev = None
                    self.ev_wsp = None
                self.ev_msg = tr
        self.ev_target = 1. if tr else 0.

    def advance_event(self, now):
        """Physics runs once per painted frame (60 Hz), not per model update, so the motion stays smooth."""
        dt = min(.04, now - self.ev_t) if self.ev_t is not None else 0.
        self.ev_t = now
        target = getattr(self, 'ev_target', 0.)
        k, d = 190., (15. if target else 21.)       # soft open with a little overshoot, calm close
        n = max(1, int(dt / .004)); h = dt / n
        for _ in range(n):
            self.ev_v += ((target - self.ev) * k - self.ev_v * d) * h
            self.ev += self.ev_v * h
        self.ev_xf.step(dt)
        if not self.ev_xf.moving:
            self.ev_prev = None
        if self.ev_wsp is not None:
            self.ev_wsp.step(dt)
        if not target and abs(self.ev) < .002 and abs(self.ev_v) < .01:
            self.ev = 0.; self.ev_v = 0.; self.ev_msg = None; self.ev_prev = None; self.ev_wsp = None

    def event_active(self):
        return self.ev_msg is not None or abs(self.ev) > .002

    def moving(self, now):
        return (super().moving(now) or self.focus.moving(now) or self.event_active() or self.ev_prev is not None
                or any(m.moving(now) for m in self.expand.values()))

    # ---- geometry ----------------------------------------------------------------------------
    def layout(self, c, ruler, now):
        """Item centres/widths on the unscrolled tape, then scrolled so `focus` sits at the index."""
        pos = self.focus.at(now); n = len(self.items)
        if not n: return [], [], 0.
        lo = max(0, min(n-1, math.floor(pos))); hi = min(n-1, lo+1); frac = pos-lo
        widths = []; gains = []
        for k, it in enumerate(self.items):
            e = smooth(self.expand[it['ws']].at(now)) if it['ws'] in self.expand else 0.
            m = smooth(1-abs(k-pos)) if it['column'] is not None else 0.
            extra = (text_width(c, it['app'] + (f" ·{it['members']}" if it['members'] > 1 else ''), self.LABEL_SIZE)+13-FULL) if it['column'] is not None else 0.
            widths.append(SMALL+(FULL-SMALL)*e+extra*m); gains.append(e)
        xs = []; x = 0.
        for k, it in enumerate(self.items):
            if k:
                x += GAP+(GROUP_GAP-GAP if it['wi'] != self.items[k-1]['wi'] else 0)
            xs.append(x+widths[k]/2); x += widths[k]
        focus_x = xs[lo]+(xs[hi]-xs[lo])*frac
        shift = ruler.width/2-focus_x
        return [v+shift for v in xs], widths, pos

    def toggle_panel(self):
        """Ask the panel process (ruler_panel.py) to open or close."""
        p = Path.home() / '.local/state/cyber-ruler'
        try:
            p.mkdir(parents=True, exist_ok=True)
            tmp = p / 'panel-cmd.tmp'
            tmp.write_text(json.dumps({'cmd': 'toggle', 'seq': int(time.time() * 1000)}))
            os.replace(tmp, p / 'panel-cmd.json')
        except OSError:
            pass

    def hit_item(self, normalized, width):
        if not self.item_x: return None
        x = max(0., min(1., normalized))*width
        return min(range(len(self.item_x)), key=lambda k: abs(self.item_x[k]-x))

    def window_action(self, ruler, command, now):
        kind = command.get('kind')
        if kind == 'window-click':
            k = self.hit_item(float(command.get('value', 0)), ruler.width)
            if k is None: return None
            it = self.items[k]
            if it['window'] is None:
                return {'Action': {'FocusWorkspace': {'reference': {'Id': it['ws']}}}}
            if k == self.focus_index and getattr(ruler, 'panel', False):
                self.toggle_panel()
                return None
            if k == self.focus_index and it['members'] > 1:
                ws = next(w for w in ruler.workspaces if w['id'] == it['ws'])
                members = ws['columns'][it['column']]['windows']
                cur = next((i for i, m in enumerate(members) if m['id'] == ws.get('focused_window')), 0)
                return {'Action': {'FocusWindow': {'id': members[(cur+1) % len(members)]['id']}}}
            return {'Action': {'FocusWindow': {'id': it['window']}}}
        if kind == 'window-step':
            ws = next((w for w in ruler.workspaces if w['id'] == ruler.active_id), None)
            windows = [m for col in (ws or {}).get('columns', []) for m in col['windows']]
            if not windows: return None
            cur = next((i for i, m in enumerate(windows) if m['id'] == ws.get('focused_window')), 0)
            return {'Action': {'FocusWindow': {'id': windows[max(0, min(len(windows)-1, cur+int(command.get('value', 0))))]['id']}}}
        return None

    # ---- paint -------------------------------------------------------------------------------
    def paint(self, ruler, now):
        width, height = ruler.width, ruler.height
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width*2, height*2)
        c = cairo.Context(surface); c.scale(2, 2)
        accent = self.accent_color(ruler); center = width/2; cy = height/2+2
        if not ruler.workspaces or not self.items:
            label(c, 'NIRI', center, height/2+3, 8, GRAY, .55); return surface
        xs, widths, pos = self.layout(c, ruler, now)
        self.advance_event(now)
        island = bool(getattr(ruler, 'island', False))
        evk = max(0., min(1.2, self.ev))
        self.item_x = xs
        hover_x = ruler.hover*width if ruler.hover >= 0 else None
        hover_k = self.hit_item(ruler.hover, width) if hover_x is not None else None
        # workspace number floats above the active group
        active = next((w for w in ruler.workspaces if w['id'] == ruler.active_id), ruler.workspaces[0])
        label(c, f"{active['idx']:02}", center, 8.5, 7, accent, .9*(1-min(1., evk)))
        # hairlines between workspace groups
        for k in range(1, len(self.items)):
            if self.items[k]['wi'] != self.items[k-1]['wi']:
                x = (xs[k]-widths[k]/2+xs[k-1]+widths[k-1]/2)/2
                a = self.fade(x, width)*.4
                if a > .01:
                    c.set_source_rgba(*GRAY, a); c.set_line_width(.8); c.set_line_cap(cairo.LINE_CAP_ROUND)
                    c.move_to(x, cy-6); c.line_to(x, cy+6); c.stroke()
        floating_marks = []
        for k, it in enumerate(self.items):
            x = xs[k]; a = self.fade(x, width)*(1-min(1., evk))
            if a <= .001: continue
            e = smooth(self.expand[it['ws']].at(now)) if it['ws'] in self.expand else 0.
            m = smooth(1-abs(k-pos)) if it['column'] is not None else 0.
            near = 1. if hover_k == k else 0.
            if it['window'] is None:                                  # empty workspace: hollow dot
                c.set_source_rgba(*GRAY, a*(.35+.25*near)); c.set_line_width(.9)
                c.arc(x, cy, 2.1, 0, math.tau); c.stroke(); continue
            h = (4.+(7.5-4.)*e)+7.*m+1.5*near
            rgb = ORANGE if it['urgent'] else mix(mix(GRAY, WHITE, .2*e), accent, m)
            alpha = a*(.28+.3*e+.42*m+.25*near)
            w = widths[k]
            if m > .05 and not island: soft_glow(c, x, cy, w, h, cy, height-cy, rgb, .65*m*a)
            fill_capsule(c, x, cy+.6, w, h, (0, 0, 0), alpha*.3)
            capsule(c, x, cy, w, h)
            body = cairo.LinearGradient(0, cy-h/2, 0, cy+h/2)
            body.add_color_stop_rgba(0, *mix(rgb, WHITE, .35), alpha); body.add_color_stop_rgba(1, *rgb, alpha)
            if island and m > .05:
                capsule(c, x, cy, w, h)
                c.set_source_rgba(.016, .016, .022, min(1., alpha*1.6)*(.35+.65*m)); c.fill_preserve()
                c.set_source_rgba(1, 1, 1, .10*m*a); c.set_line_width(.7); c.stroke()
            else:
                c.set_source(body); c.fill()
            if m > .55:
                value = it['app']+(f" ·{it['members']}" if it['members'] > 1 else '')
                label(c, value, x, cy+2.6, self.LABEL_SIZE, (.97, .97, 1.) if island else (.04, .06, .1), (m-.55)/.45*a)
            elif it['floating']:
                c.set_source_rgba(*WHITE, a*.8); c.arc(x, cy-h/2-2.2, .9, 0, math.tau); c.fill()
        if self.ev_msg is not None and evk > .01:
            self.paint_event(c, ruler, widths, xs, center, cy, evk)
        if not ruler.connected: label(c, '!', width-9, 20, 8, ORANGE, .85)
        return surface

    def _ev_text(self, c, ruler, tr):
        """The message trimmed to fit, and its drawn width."""
        self.feed.font(c, 10, True)
        text = tr.get('label', '')
        room = ruler.width - 16. - 16 - 10 - 7 - 16
        while len(text) > 2 and c.text_extents(text).x_advance > room:
            text = text[:-2] + '…' if not text.endswith('…') else text[:-2] + '…'
        return text, c.text_extents(text).x_advance

    def paint_event(self, c, ruler, widths, xs, center, cy, evk):
        """The focused pill grows into a black island carrying the message; a new message morphs the island
        (width springs, text cross-fades) instead of swapping; then it shrinks back into the pill."""
        tr = self.ev_msg
        k = self.focus_index
        w0 = max(widths[k], 14.) if self.items and k < len(widths) else 14.
        h0 = 14.5 if self.items else 8.
        feed = self.feed
        text, tw = self._ev_text(c, ruler, tr)
        want = min(ruler.width - 16., 16 + 10 + 7 + tw + 16)
        if self.ev_wsp is None:
            self.ev_wsp = EvSpring(want, omega=20, zeta=.78)
        self.ev_wsp.t = want
        want_now = self.ev_wsp.x
        e = max(0., min(1.2, evk))
        ew = e ** 1.9                      # width lags behind, so the island is never wide and empty
        w = w0 + (want_now - w0) * ew
        h = h0 + (22. - h0) * min(1., e) ** 1.4
        cx = (xs[k] if self.items and k < len(xs) else center)
        cx = cx + (center - cx) * min(1., e)
        x0 = max(2., min(ruler.width - 2. - w, cx - w / 2))
        alpha = min(1., e * 1.5)
        c.save()
        c.push_group()
        feed.rr(c, x0, cy - h / 2 + .5, w, h, h / 2)
        c.set_source_rgba(0, 0, 0, .45); c.fill()
        feed.rr(c, x0, cy - h / 2, w, h, h / 2)
        c.set_source_rgb(.016, .016, .022); c.fill_preserve()
        c.set_source_rgba(1, 1, 1, .10); c.set_line_width(.7); c.stroke()
        show = max(0., min(1., (e - .22) / .28))
        if show > .01:
            feed.rr(c, x0, cy - h / 2, w, h, h / 2)
            c.clip()
            xf = max(0., min(1., self.ev_xf.x)) if self.ev_prev is not None else 1.0
            mid = x0 + w / 2
            layers = []
            if self.ev_prev is not None and xf < .999:
                layers.append((self.ev_prev, (1 - xf) * show, -3.0 * xf))
            layers.append((tr, xf * show, 3.0 * (1 - xf)))
            for msg, a_, dy in layers:
                if a_ < .01:
                    continue
                label, mtw = self._ev_text(c, ruler, msg)
                cxl = mid - (10 + 7 + mtw) / 2
                c.push_group()
                feed.msg_icon(c, cxl + 5, cy + dy, msg.get('icon'), (.97, .97, 1.), accent_of(ruler))
                feed.font(c, 10, True)
                c.set_source_rgba(.97, .97, 1., 1)
                c.move_to(cxl + 10 + 7, cy + 3.6 + dy); c.show_text(label)
                c.pop_group_to_source(); c.paint_with_alpha(a_)
        c.pop_group_to_source(); c.paint_with_alpha(alpha)
        c.restore()


def accent_of(ruler):
    return ruler.accent_rgb(DEFAULT)

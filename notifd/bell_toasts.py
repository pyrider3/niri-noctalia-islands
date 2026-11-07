"""'Bell' notification style.

New notifications are shaken out of the bar's bell: each one flies from the bell to its place under the bar (tilting
with its speed), the bell rings as it leaves, and when the card times out it flies back into the bell. Clicking the
bell opens the floating history cards (stack.py), which fly out of the bell the same way.
"""
import json
import threading
import time
from pathlib import Path

import cairo
from gi.repository import GLib

import barpos
import gfx
import stack as S
from capsule_notice import Item
from gfx import THEME, clamp, rrect
from stack import CM, PADX, Card, Stack

MAX_TOASTS = 4
BELL_STATUS = Path.home() / '.local/state/notifd-bell/status.json'
STACK_RIGHT = 26
GAP = 10


class ToastStack(Stack):
    """Live notification cards; same drawing/animation as the history stack, but timed and with action buttons."""

    def __init__(self, app, mgr, on_action, on_closed):
        super().__init__(app, mgr, lambda n: Item(n, pills=True), STACK_RIGHT, 0, on_closed)
        self.on_action = on_action
        self.more = 0

    # ------------------------------------------------------------------ cards
    def ids(self):
        return {c.n.id for c in self.cards if not c.gone}

    def add(self, n):
        self._ensure_window()
        for c in self.cards:
            if c.n.id == n.id and not c.gone:          # replaced notification: refresh in place
                c.n = n
                c.item = self.make_item(n)
                c.cache = None
                c.item.remaining = c.item.total
                self._show()
                return
        c = Card(self.make_item(n), 0)
        c.dx.snap(0)
        self.cards.insert(0, c)
        live = [x for x in self.cards if not x.gone]
        for old in live[MAX_TOASTS:]:
            self._leave(old, timeout=False)
        self._show()

    def _show(self):
        if self.win is not None and not self.win.get_visible():
            self.win.present()
        self._start_frames()

    def remove(self, nid):
        for c in self.cards:
            if c.n.id == nid and not c.gone:
                self._leave(c, timeout=False)

    def clear(self):
        for c in self.cards:
            if not c.gone:
                self._leave(c, timeout=False)

    def _leave(self, c, timeout=True):
        """Fly back into the bell."""
        c.gone = True
        c.dx.t = 0.0
        c.a.t = 0.0
        c.a.z, c.a.o = .95, 20.0
        S.kick(.6)
        if timeout:
            self.on_closed(c.n.id, 1)
        self._start_frames()

    def _dismiss(self, c, direction=1):
        c.gone = True
        c.dx.t = 460.0 * direction
        c.a.t = 0.0
        self.mgr.dismiss_from_center(c.n.id)

    # ------------------------------------------------------------- overrides
    def _layout(self):
        y = 10.0
        for c in self.cards:
            if c.gone:
                continue
            c.top = y
            y += c.item.h + GAP
        return y

    def _hit_chip(self):
        return None

    def _render_card(self, c, hov, xhot):
        surf = super()._render_card(c, hov, xhot)
        if c.item.pills:
            cr = cairo.Context(surf)
            th = THEME
            for p in c.item.pills:
                px, py = CM + p['x'], CM + p['y']
                rrect(cr, px, py, p['w'], p['h'], p['h'] / 2)
                cr.set_source_rgba(*th.accent, .2)
                cr.fill()
                gfx.draw_layout(cr, p['lay'], px + 14, py + (p['h'] - gfx.text_size(p['lay'])[1]) / 2, (*th.accent, 1))
        return surf

    def _pill_at(self, c, pt):
        for p in c.item.pills:
            x, y = PADX + p['x'], c.y.x + p['y']
            if x <= pt[0] <= x + p['w'] and y <= pt[1] <= y + p['h']:
                return p
        return None

    def _drag_end(self, g, dx, dy):
        c, self.drag_card = self.drag_card, None
        press, self.press = self.press, None
        if press is None or c is None or c.gone:
            return
        if abs(dx) <= 6 and abs(dy) <= 6:
            pill = self._pill_at(c, press)
            if pill is not None:
                self.on_action(c.n.id, pill['key'])
                self._dismiss(c)
            elif self._on_close(c, press):
                self._dismiss(c)
            elif c.item.default_action:
                self.on_action(c.n.id, 'default')
                self._dismiss(c)
            return
        if abs(dx) > 90:
            self._dismiss(c, 1 if dx > 0 else -1)
        else:
            c.dx.t = 0.0
            self._start_frames()

    def _frame(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        if self._fl and now - self._fl < .0155:
            return GLib.SOURCE_CONTINUE
        dt = min(.05, now - self._fl) if self._fl else 1 / 60
        self._fl = now
        THEME.refresh()
        total = self._layout()
        t = time.monotonic()
        hovering = self._card_at(self.pointer) is not None
        busy = False
        for c in list(self.cards):
            if not c.gone:
                if c.start is None:
                    c.start = t
                    S.kick(1.0)
                c.a.t = 1.0
                c.a.z, c.a.o = .72, 15.0
                it = c.item
                if it.total and not hovering:
                    it.remaining -= dt
                    if it.remaining <= 0:
                        self._leave(c)
                if not c.y_set:
                    c.y.snap(c.top)
                    c.y_set = True
                c.y.t = c.top
            for sp in (c.a, c.y, c.dx):
                sp.step(dt)
                busy = busy or not sp.settled
        self.cards = [c for c in self.cards if not (c.gone and c.a.x < .02 and c.a.settled)]
        need = (int(total) + 40 + 19) // 20 * 20
        if need != self.height:
            self.height = need
            self.da.set_content_height(need + S.TOPPAD)
        self.da.queue_draw()
        self._update_region()
        if not self.cards and not busy:
            self.win.set_visible(False)
            self.frame_tick = None
            self.region_key = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def shutdown(self):
        super().shutdown()


class BellLayer:
    """Presenter: live toasts + history stack, both flying out of the bell."""

    def __init__(self, app, on_action, on_closed):
        self.app = app
        self.on_action = on_action
        self.on_closed = on_closed
        self.mgr = None
        self.toasts = None
        self.stack = None          # history cards (the manager refreshes it when the history changes)
        self.bell_r = None         # measured: bell centre, px from the screen's right edge
        self._loc_t = 0.0
        self._locating = False
        GLib.timeout_add(800, self._prewarm)
        GLib.timeout_add(3000, lambda: self.locate() or False)
        GLib.timeout_add_seconds(60, lambda: self.locate() or True)

    def _ensure(self):
        if self.toasts is None and self.mgr is not None:
            self.toasts = ToastStack(self.app, self.mgr, self.on_action, self.on_closed)
            self.stack = Stack(self.app, self.mgr, lambda n: Item(n, pills=False), STACK_RIGHT, 0, self.on_closed)
            self._apply_bell()
        return self.toasts is not None

    def _prewarm(self):
        if self._ensure():
            self.stack._ensure_window()
        return False

    # ---- where the bell really is (measured on screen)
    def locate(self):
        if self._locating:
            return
        self._locating = True

        def work():
            res = None
            try:
                st = json.loads(BELL_STATUS.read_text())
                mk = st.get('marker')
                if mk:
                    res = barpos.find_marker(tuple(int(v) for v in mk), min_run=2)
            except (OSError, ValueError, TypeError):
                pass
            GLib.idle_add(self._located, res)
        threading.Thread(target=work, daemon=True).start()

    def _located(self, res):
        self._locating = False
        self._loc_t = time.monotonic()
        if res:
            left, right, lw = res
            self.bell_r = lw - (left + right) / 2      # the clapper sits in the middle of the bell
            self._apply_bell()
        return False

    def _apply_bell(self):
        if self.bell_r is None:
            return
        for s in (self.toasts, self.stack):
            if s is not None:
                s.set_bell(self.bell_r)

    def set_bell_hover(self, entered):
        if entered and time.monotonic() - self._loc_t > 2.0:
            self.locate()

    # ---- presenter API used by the manager
    def ids(self):
        return self.toasts.ids() if self.toasts else set()

    def show(self, n):
        if not self._ensure():
            return
        if self.stack.is_open:
            self.stack.refresh()
            return
        self.toasts.add(n)

    def close_id(self, nid, reason=3):
        if self.toasts:
            self.toasts.remove(nid)

    def clear(self):
        if self.toasts:
            self.toasts.clear()

    def shutdown(self):
        for s in (self.toasts, self.stack):
            if s is not None:
                s.shutdown()
        self.toasts = self.stack = None

    def handle_bell_click(self):
        if not self._ensure():
            return False
        self.toasts.clear()
        self.stack.toggle()
        return True

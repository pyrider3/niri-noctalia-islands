"""Event source for the ruler's black-island mode: reuses the event-center sensors, draws nothing itself."""
import json
import subprocess
import threading
import time
from pathlib import Path

from events_core import Hub, Sensors


class _NoNiri:
    def take_events(self):
        return []


class Feed(Hub):
    """A Hub without a canvas: poll() turns sensor changes into self.trans = {label, icon, t0, end}."""

    def __init__(self):
        self.sensors = Sensors()
        self.prev = {}
        self.first = True
        self.trans = None
        self.niri = _NoNiri()
        self.ime = None            # fcitx5's current input method, polled in a thread
        self.ime_seen = None
        threading.Thread(target=self._ime_loop, daemon=True).start()
        self.pending = []
        self.last_ts = self._feed().get('ts', 0)    # ignore whatever was announced before we started

    NAMES = {'pinyin': 'Pinyin', 'keyboard-us': 'English (US)', 'shuangpin': 'Shuangpin', 'wubi': 'Wubi', 'rime': 'Rime'}

    def _ime_loop(self):
        while True:
            try:
                out = subprocess.check_output(['fcitx5-remote', '-n'], timeout=1.5, stderr=subprocess.DEVNULL).decode().strip()
                self.ime = out or self.ime
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(.25)

    @staticmethod
    def _feed():
        try:
            d = json.loads((Path.home() / '.local/state/notifd/island-feed.json').read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    MIN_SHOW = .9          # seconds a message stays before the next one takes over

    def trigger(self, kind, now, **kw):
        """Queue a message that arrives while another one has only just appeared, so each gets seen."""
        dur = kw.pop('dur', None)
        if kind == 'msg' and self.trans and now < self.trans['t0'] + self.MIN_SHOW:
            self.pending.append(dict(kw, dur=dur))
            return
        super().trigger(kind, now, **kw)
        if dur is not None and self.trans:
            self.trans['end'] = now + dur

    def poll(self):
        now = time.monotonic()
        self.poll_events(now)
        if self.pending and (not self.trans or now >= self.trans['t0'] + self.MIN_SHOW):
            self.trigger('msg', now, **self.pending.pop(0))
        if self.ime and self.ime != self.ime_seen:
            first = self.ime_seen is None
            self.ime_seen = self.ime
            if not first:
                name = self.NAMES.get(self.ime) or self.ime.replace('keyboard-', '').replace('-', ' ').title()
                self.trigger('msg', now, icon='kbd', label=name)
        d = self._feed()
        if d.get('ts', 0) > self.last_ts:
            self.last_ts = d['ts']
            title, artist = str(d.get('title', '')), str(d.get('artist', ''))
            self.trigger('msg', now, icon='music', label=title + (' · ' + artist if artist else ''), dur=3.6)
        if self.trans and (self.trans.get('kind') != 'msg' or now > self.trans['end']):
            self.trans = None
        return self.trans

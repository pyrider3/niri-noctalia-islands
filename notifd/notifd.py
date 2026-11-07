#!/usr/bin/env python3
"""notifd: a freedesktop notification daemon with animated toasts and a notification centre.

Run with:  LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so python3 notifd.py
"""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# gtk4-layer-shell must be loaded before libwayland, and GTK's default renderer is extremely slow on this
# machine (frames take ~1 s); `ngl` runs at normal frame rates. Re-exec once with the right environment.
_LAYER = '/usr/lib/libgtk4-layer-shell.so'
if _LAYER not in os.environ.get('LD_PRELOAD', '') and os.path.exists(_LAYER):
    _env = dict(os.environ, LD_PRELOAD=(_LAYER + ' ' + os.environ.get('LD_PRELOAD', '')).strip())
    _env.setdefault('GSK_RENDERER', 'gl')
    os.execvpe(sys.executable, [sys.executable] + sys.argv, _env)
os.environ.setdefault('GSK_RENDERER', 'gl')

import dbus  # noqa: E402
import dbus.service  # noqa: E402
from dbus.mainloop.glib import DBusGMainLoop  # noqa: E402

DBusGMainLoop(set_as_default=True)

import gi  # noqa: E402

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

import gfx  # noqa: E402
import model  # noqa: E402
from model import CRITICAL, LOW, NORMAL, Notif  # noqa: E402
from toasts import ToastLayer  # noqa: E402

THEME_FILE = model.STATE_DIR / 'theme.json'
STYLES = ('card', 'frost', 'island', 'capsule', 'bell')


def read_theme():
    try:
        d = json.loads(THEME_FILE.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def read_style():
    st = read_theme().get('style')
    return st if st in STYLES else 'card'


SOUND_DIR = '/usr/share/sounds/freedesktop/stereo/'
EFFECTS = {'message': 'message-new-instant', 'message2': 'message', 'bell': 'bell', 'complete': 'complete',
           'attention': 'window-attention'}
CRITICAL_SOUND = 'dialog-warning'

LOG = model.STATE_DIR / 'notifd.log'


def log(msg):
    try:
        model.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open('a') as f:
            f.write(msg.rstrip() + '\n')
    except OSError:
        pass


def guarded(fn):
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:
            log(traceback.format_exc())
            raise
    wrapper.__name__ = fn.__name__
    return wrapper


class Manager:
    def __init__(self, app):
        self.app = app
        self.history = model.load_history()
        self.next_id = max([n.id for n in self.history] + [0]) + 1
        self.unread = 0
        self.dnd = False
        try:
            self.dnd = bool(json.loads(model.STATE_FILE.read_text()).get('dnd'))
        except (OSError, ValueError):
            pass
        self.service = None
        self.center = None
        self.style = read_style()
        self.presenter = self.make_presenter(self.style)
        self._theme_mtime = None
        self.sound = True
        self.effect = 'message'
        self._last_sound = 0.0
        GLib.timeout_add(700, self._watch_theme)
        self._save_id = None
        self.write_state()

    # ------------------------------------------------------------- presenters
    def make_presenter(self, style):
        try:
            if style == 'island':
                from island import IslandLayer
                return IslandLayer(self.app, self.invoke_action, self.toast_closed)
            if style == 'bell':
                from bell_toasts import BellLayer
                p = BellLayer(self.app, self.invoke_action, self.toast_closed)
                p.mgr = self
                return p
            if style == 'capsule':
                from capsule_notice import CapsuleLayer
                p = CapsuleLayer(self.app, self.invoke_action, self.toast_closed)
                p.mgr = self
                return p
        except Exception:
            log('presenter %s failed, using card: %s' % (style, traceback.format_exc()))
            style = 'card'
        return ToastLayer(self.app, self.invoke_action, self.toast_closed, style='frost' if style == 'frost' else 'card')

    def set_style(self, style):
        if style not in STYLES or style == self.style and self.presenter is not None:
            return
        old = self.presenter
        self.presenter = None
        try:
            old.shutdown()
        except Exception:
            log(traceback.format_exc())
        self.style = style
        self.presenter = self.make_presenter(style)
        self.write_state()

    def _watch_theme(self):
        try:
            mt = THEME_FILE.stat().st_mtime_ns
        except OSError:
            return True
        if mt != self._theme_mtime:
            self._theme_mtime = mt
            try:
                th = read_theme()
                self.sound = th.get('sound', True) is not False
                self.effect = th.get('effect') if th.get('effect') in EFFECTS else 'message'
                self.set_style(read_style())
            except Exception:
                log(traceback.format_exc())
        return True

    def presenter_click(self):
        """Click on the bar bell: the capsule style handles it itself, others open the centre."""
        p = self.presenter
        if p is not None and getattr(p, 'handle_bell_click', None) and p.handle_bell_click():
            return
        self.toggle_center()

    # ----------------------------------------------------------- bookkeeping
    def write_state(self):
        try:
            model.write_json(model.STATE_FILE, dict(count=len(self.history), unread=self.unread, dnd=self.dnd, style=self.style))
        except OSError:
            pass

    def save_later(self):
        if self._save_id is None:
            self._save_id = GLib.timeout_add(600, self._flush)

    def _flush(self):
        self._save_id = None
        model.save_history(self.history)
        return False

    # ------------------------------------------------------------ D-Bus side
    def _island_routes_music(self):
        """True when the cyber-ruler's black island is on and wants to announce new tracks itself."""
        try:
            import tomllib
            p = os.path.expanduser('~/.local/state/noctalia/settings.toml')
            mt = os.stat(p).st_mtime
            if getattr(self, '_ir_mt', None) != mt:
                with open(p, 'rb') as f:
                    d = tomllib.load(f).get('plugin_settings', {}).get('local/cyber-ruler', {})
                self._ir = bool(d.get('events') and d.get('theme') == 'merged')
                self._ir_mt = mt
            return self._ir
        except Exception:
            return False

    def _island_feed(self, nid, summary, body, icon):
        try:
            tmp = os.path.expanduser('~/.local/state/notifd/island-feed.json.tmp')
            with open(tmp, 'w') as f:
                json.dump({'id': nid, 'title': summary, 'artist': body, 'cover': icon, 'ts': time.time()}, f, ensure_ascii=False)
            os.replace(tmp, os.path.expanduser('~/.local/state/notifd/island-feed.json'))
        except OSError:
            pass

    def notify(self, app_name, replaces_id, icon, summary, body, actions, hints, timeout):
        hints = {str(k): v for k, v in hints.items()}
        urgency = int(hints.get('urgency', NORMAL))
        category = str(hints.get('category', ''))
        resident = bool(hints.get('resident', False))
        transient = bool(hints.get('transient', False))
        app = str(app_name) or str(hints.get('desktop-entry', ''))
        icon = str(icon)
        pb = None
        for key in ('image-data', 'image_data', 'icon_data'):
            if key in hints:
                pb = gfx.pixbuf_from_image_data(hints[key])
                if pb is not None:
                    break
        for key in ('image-path', 'image_path'):
            if key in hints and not pb:
                icon = str(hints[key])
        pairs = [(str(actions[i]), str(actions[i + 1])) for i in range(0, len(actions) - 1, 2)]
        known = {n.id for n in self.history} | self.presenter.ids()
        rid = int(replaces_id)
        if rid and rid in known:
            nid = rid
        else:
            nid = self.next_id
            self.next_id += 1
        n = Notif(nid, app, str(summary), str(body), icon, pairs, urgency, int(timeout), category,
                  resident, transient, pb, desktop=str(hints.get('desktop-entry', '')))
        if not transient:
            for i, old in enumerate(self.history):
                if old.id == nid:
                    self.history[i] = n
                    break
            else:
                self.history.append(n)
            del self.history[:-150]
            self.save_later()
        if app.lower() == 'kew' and self._island_routes_music():
            self._island_feed(nid, str(summary), str(body), icon)     # the ruler island announces it
            self.write_state()
            return nid
        self.unread += 1
        if self.center is not None and self.center.is_open:
            self.center.refresh(new_id=nid)
            self.unread = 0
        elif self.dnd and urgency < CRITICAL:
            pass
        else:
            self.presenter.show(n)
            self.play_sound(urgency)
        self.write_state()
        return nid

    def play_sound(self, urgency):
        """Low: silent. Normal: the chosen soft sound. Critical: a more insistent one. (DND never reaches here
        for non-critical notifications.)"""
        if not self.sound or urgency == LOW:
            return
        now = time.monotonic()
        if now - self._last_sound < .35:      # a burst of notifications gets one sound
            return
        self._last_sound = now
        name = CRITICAL_SOUND if urgency == CRITICAL else EFFECTS.get(self.effect, 'message-new-instant')
        path = SOUND_DIR + name + '.oga'
        if os.path.exists(path):
            try:
                p = subprocess.Popen(['paplay', '--client-name=notifd-sound', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                threading.Thread(target=p.wait, daemon=True).start()      # reap it, no zombies
            except OSError:
                pass

    def close(self, nid):
        self.presenter.close_id(nid, 3)
        self.remove_history(nid)

    def remove_history(self, nid, reason=None):
        self.history = [n for n in self.history if n.id != nid]
        self.save_later()
        self.write_state()
        if self.center is not None:
            self.center.refresh()
        self._refresh_stack()

    def _refresh_stack(self):
        st = getattr(self.presenter, 'stack', None)
        if st is not None and st.is_open:
            st.refresh()

    def invoke_action(self, nid, key):
        if self.service:
            self.service.ActionInvoked(nid, key)

    def toast_closed(self, nid, reason):
        if self.service:
            self.service.NotificationClosed(nid, reason)

    # ---------------------------------------------------------------- control
    def toggle_dnd(self):
        self.set_dnd(not self.dnd)

    def set_dnd(self, value):
        self.dnd = bool(value)
        self.write_state()
        if self.center is not None:
            self.center.refresh()

    def clear_all(self):
        for n in self.history:
            if self.service:
                self.service.NotificationClosed(n.id, 2)
        self.history = []
        self.unread = 0
        self.save_later()
        self.write_state()
        if self.center is not None:
            self.center.refresh(cleared=True)

    def toggle_center(self):
        if self.center is None:
            log('centre not built yet')
            return
        self.center.toggle()

    def dismiss_from_center(self, nid):
        if self.service:
            self.service.NotificationClosed(nid, 2)
        self.presenter.close_id(nid, 2)
        self.history = [n for n in self.history if n.id != nid]
        self.save_later()
        self.write_state()
        if self.center is not None:
            self.center.refresh()

    def center_opened(self):
        self.unread = 0
        self.write_state()


class NotifyService(dbus.service.Object):
    IFACE = 'org.freedesktop.Notifications'

    def __init__(self, bus, mgr):
        name = dbus.service.BusName(self.IFACE, bus, do_not_queue=True)
        super().__init__(name, '/org/freedesktop/Notifications')
        self.mgr = mgr

    @dbus.service.method(IFACE, in_signature='', out_signature='as')
    def GetCapabilities(self):
        return ['actions', 'body', 'body-markup', 'icon-static', 'persistence']

    @dbus.service.method(IFACE, in_signature='susssasa{sv}i', out_signature='u')
    def Notify(self, app, rid, icon, summary, body, actions, hints, timeout):
        try:
            return self.mgr.notify(app, rid, icon, summary, body, actions, hints, timeout)
        except Exception:
            log(traceback.format_exc())
            return 0

    @dbus.service.method(IFACE, in_signature='u', out_signature='')
    def CloseNotification(self, nid):
        try:
            self.mgr.close(int(nid))
        except Exception:
            log(traceback.format_exc())

    @dbus.service.method(IFACE, in_signature='', out_signature='ssss')
    def GetServerInformation(self):
        return 'notifd', 'pr', '1.0', '1.2'

    @dbus.service.signal(IFACE, signature='uu')
    def NotificationClosed(self, nid, reason):
        pass

    @dbus.service.signal(IFACE, signature='us')
    def ActionInvoked(self, nid, key):
        pass


class ControlService(dbus.service.Object):
    IFACE = 'dev.pr.Notifd'

    def __init__(self, bus, mgr):
        name = dbus.service.BusName(self.IFACE, bus, do_not_queue=True)
        super().__init__(name, '/dev/pr/Notifd')
        self.mgr = mgr

    @staticmethod
    def _run(fn, *args):
        try:
            fn(*args)
        except Exception:
            log(traceback.format_exc())
        return False

    @dbus.service.method(IFACE, in_signature='', out_signature='')
    def ToggleCenter(self):
        GLib.idle_add(self._run, self.mgr.toggle_center)

    @dbus.service.method(IFACE, in_signature='', out_signature='')
    def CloseCenter(self):
        def go():
            if self.mgr.center is not None:
                self.mgr.center.close()
        GLib.idle_add(self._run, go)

    @dbus.service.method(IFACE, in_signature='', out_signature='')
    def ToggleDND(self):
        GLib.idle_add(self._run, self.mgr.toggle_dnd)

    @dbus.service.method(IFACE, in_signature='b', out_signature='')
    def SetDND(self, value):
        GLib.idle_add(self._run, self.mgr.set_dnd, bool(value))

    @dbus.service.method(IFACE, in_signature='', out_signature='')
    def ClearAll(self):
        GLib.idle_add(self._run, self.mgr.clear_all)

    @dbus.service.method(IFACE, in_signature='s', out_signature='')
    def SetStyle(self, style):
        if str(style) in STYLES:
            model.write_json(THEME_FILE, dict(read_theme(), style=str(style)))

    @dbus.service.method(IFACE, in_signature='', out_signature='')
    def BellClick(self):
        GLib.idle_add(self._run, self.mgr.presenter_click)

    @dbus.service.method(IFACE, in_signature='b', out_signature='')
    def BellHover(self, entered):
        def go(v):
            p = self.mgr.presenter
            if p is not None and getattr(p, 'set_bell_hover', None):
                p.set_bell_hover(v)
        GLib.idle_add(self._run, go, bool(entered))

    @dbus.service.method(IFACE, in_signature='', out_signature='s')
    def GetState(self):
        return json.dumps(dict(count=len(self.mgr.history), unread=self.mgr.unread, dnd=self.mgr.dnd))


def main():
    app = Gtk.Application(application_id='dev.pr.notifd', flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(app):
        css = Gtk.CssProvider()
        css.load_from_string('''
            window.notifd, window.notifd-center { background: transparent; }
            window.notifd-catcher { background-color: rgba(0,0,0,0); transition: background-color 320ms ease; }
            window.notifd-catcher.dim { background-color: rgba(0,0,0,0.34); }
        ''')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        mgr = Manager(app)
        try:
            from center import Center
            mgr.center = Center(app, mgr)
        except ImportError:
            log('centre module not available yet')
        bus = dbus.SessionBus()
        try:
            mgr.service = NotifyService(bus, mgr)
        except dbus.exceptions.NameExistsException:
            print('another notification daemon already owns org.freedesktop.Notifications', file=sys.stderr)
            app.quit()
            return
        mgr.control = ControlService(bus, mgr)
        if os.environ.get('NOTIFD_DEBUG'):
            (model.STATE_DIR / 'bus-address').write_text(os.environ.get('DBUS_SESSION_BUS_ADDRESS', ''))
        log('notifd started')

    app.connect('activate', on_activate)
    app.hold()
    if os.environ.get('NOTIFD_PROFILE'):
        import cProfile
        pr = cProfile.Profile()
        pr.enable()

        def stop():
            pr.disable()
            pr.dump_stats(os.environ['NOTIFD_PROFILE'])
            app.quit()
            return False
        GLib.timeout_add_seconds(int(os.environ.get('NOTIFD_PROFILE_SECS', '12')), stop)
    sys.exit(app.run(None))


if __name__ == '__main__':
    main()

"""Adapters: Noctalia settings (via `noctalia msg`), JSON preference files, niri; plus snapshots for undo/rollback."""
import ast
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

HOME = Path.home()
BACKUPS = HOME / '.config/desk-settings/backups'
NOCTALIA_SETTINGS = HOME / '.local/state/noctalia/settings.toml'
_snapped = set()


def snapshot(path):
    """Copy a file into backups/<session>/ the first time this session touches it."""
    path = Path(path)
    if path in _snapped or not path.exists():
        return
    _snapped.add(path)
    d = BACKUPS / time.strftime('%Y%m%d-%H%M%S')
    d.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(path, d / path.name)
    except OSError:
        pass


def run(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, '', str(e)


# ------------------------------------------------------------------ Noctalia
def _toml_literal(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "") + "'"


_cfg_cache = {'mt': None, 'data': {}}


def _cfg():
    """Noctalia's settings.toml, parsed (cached by mtime) - reading is instant, writing goes through `noctalia msg`."""
    import tomllib
    try:
        mt = NOCTALIA_SETTINGS.stat().st_mtime_ns
    except OSError:
        return {}
    if mt != _cfg_cache['mt']:
        try:
            _cfg_cache['data'] = tomllib.loads(NOCTALIA_SETTINGS.read_text())
            _cfg_cache['mt'] = mt
        except (OSError, ValueError):
            pass
    return _cfg_cache['data']


def _split(path):
    parts, cur, q = [], '', False
    for ch in path:
        if ch == '"':
            q = not q
        elif ch == '.' and not q:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    parts.append(cur)
    return parts


def ncfg_get(path, default=None):
    d = _cfg()
    for k in _split(path):
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def ncfg_set(path, value):
    snapshot(NOCTALIA_SETTINGS)
    rc, out, err = run(['noctalia', 'msg', 'config-set', path, _toml_literal(value)])
    return rc == 0


def plugin_get(plugin, key, default=None):
    return ncfg_get('plugin_settings."%s".%s' % (plugin, key), default)


def plugin_set(plugin, key, value):
    """Edit [plugin_settings."<id>"] in settings.toml directly (config-set cannot parse quoted keys with '/')."""
    import re
    import tempfile
    try:
        snapshot(NOCTALIA_SETTINGS)
        p = Path(NOCTALIA_SETTINGS)
        lines = p.read_text().split('\n')
        head = '[plugin_settings."%s"]' % plugin
        lit = _toml_literal(value).replace("'", '"') if isinstance(value, str) else _toml_literal(value)
        kv = '%s = %s' % (key, lit)
        try:
            i = lines.index(head)
        except ValueError:
            while lines and lines[-1] == '':
                lines.pop()
            lines += ['', head, kv, '']
        else:
            j = i + 1
            while j < len(lines) and not lines[j].startswith('['):
                j += 1
            for k in range(i + 1, j):
                if re.match(r'\s*%s\s*=' % re.escape(key), lines[k]):
                    lines[k] = kv
                    break
            else:
                end = j
                while end > i + 1 and lines[end - 1] == '':
                    end -= 1
                lines.insert(end, kv)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent))
        with os.fdopen(fd, 'w') as f:
            f.write('\n'.join(lines))
        os.replace(tmp, p)
        run(['noctalia', 'msg', 'config-reload'])    # Noctalia keeps its own copy: without this a later config-set overwrites our edit
        return True
    except Exception:
        return False


# --------------------------------------------------------------- JSON files
def json_get(path, key, default=None):
    try:
        return json.loads(Path(path).read_text()).get(key, default)
    except (OSError, ValueError, AttributeError):
        return default


def json_set(path, key, value):
    path = Path(path)
    snapshot(path)
    try:
        cur = json.loads(path.read_text())
        if not isinstance(cur, dict):
            cur = {}
    except (OSError, ValueError):
        cur = {}
    cur[key] = value
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(cur, ensure_ascii=False))
    os.replace(tmp, path)
    return True


# ------------------------------------------------------- Wallpaper Engine
WE_DIR = HOME / '.local/share/Steam/steamapps/workshop/content/431960'
WE_DATA = HOME / '.local/state/noctalia/plugins/data/tadomika_ari/w-engine'
WE_PREFS = HOME / '.config/desk-settings/we.json'
WE_DEFAULTS = {'fps': 30, 'volume': 15, 'silent': False, 'scaling': 'fill'}


def we_list():
    out = []
    if not WE_DIR.exists():
        return out
    for d in sorted(WE_DIR.iterdir()):
        try:
            j = json.loads((d / 'project.json').read_text())
        except (OSError, ValueError):
            continue
        thumb = WE_DATA / 'thumbs' / (d.name + '.jpg')
        if not thumb.exists():
            pv = j.get('preview')
            thumb = d / pv if pv and (d / pv).exists() else None
        out.append({'id': d.name, 'title': str(j.get('title') or d.name), 'type': str(j.get('type') or '').lower(),
                    'thumb': str(thumb) if thumb else None})
    return out


def we_pref(key):
    return json_get(WE_PREFS, key, WE_DEFAULTS[key])


def we_pref_set(key, value):
    return json_set(WE_PREFS, key, value)


def we_current(output='eDP-1'):
    """The wallpaper id the running engine process was started with, or ''."""
    rc, out, _ = run(['ps', '-eo', 'args'])
    for line in out.splitlines():
        if 'linux-wallpaperengine' in line and '--bg' in line and ('--screen-root %s' % output) in line \
                and 'run-on-igpu' not in line:
            parts = line.split()
            return parts[parts.index('--bg') + 1]
    return ''


def we_stop(output='eDP-1'):
    run(['pkill', '-9', '-f', 'linux-wallpaperengine.*--screen-root %s' % output])
    time.sleep(.3)


def we_apply(wid, output='eDP-1'):
    """Replace the running wallpaper (the engine ignores SIGTERM, so SIGKILL) and start the new one."""
    if not (WE_DIR / wid / 'project.json').exists():
        return False
    we_stop(output)
    args = ['setsid', 'linux-wallpaperengine', '--screen-root', output, '--bg', wid,
            '--scaling', str(we_pref('scaling')), '--layer', 'background', '--fps', str(we_pref('fps'))]
    args += ['--silent'] if we_pref('silent') else ['--volume', str(we_pref('volume'))]
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        return False
    try:    # keep W-Engine's own record in step so its panel shows the right current one
        p = WE_DATA / 'data.json'
        d = json.loads(p.read_text())
        d.setdefault('current', {})[output] = wid
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        os.replace(tmp, p)
    except (OSError, ValueError):
        pass
    time.sleep(1.2)
    return we_current(output) == wid


# ------------------------------------------------------------ niri appearance
NIRI_DIR = HOME / '.config/niri'
NIRI_CFG = NIRI_DIR / 'config.kdl'
NIRI_APP = NIRI_DIR / 'desk-appearance.kdl'
NIRI_PREFS = HOME / '.config/desk-settings/niri-appearance.json'
NIRI_INCLUDE = 'include optional=true "desk-appearance.kdl"'
NIRI_DEFAULTS = {'gaps': 10, 'ring': 1, 'shadow': False, 'softness': 50, 'spread': 0, 'radius_on': False, 'radius': 12,
                 'passes': 4, 'offset': 5, 'noise': 15, 'saturation': 125, 'slowdown': 100}


def niri_get(key):
    return json_get(NIRI_PREFS, key, NIRI_DEFAULTS[key])


def _niri_kdl():
    g = niri_get
    L = ['// Managed by desk-settings. Delete this file (or its include in config.kdl) to roll back.',
         'layout {', '    gaps %d' % g('gaps'), '    focus-ring {', '        width %.1f' % (g('ring') / 10), '    }']
    if g('shadow'):
        L += ['    shadow {', '        on', '        softness %d' % g('softness'), '        spread %d' % g('spread'), '    }']
    L += ['}', 'blur {', '    passes %d' % g('passes'), '    offset %.1f' % g('offset'),
          '    noise %.3f' % (g('noise') / 1000), '    saturation %.2f' % (g('saturation') / 100), '}',
          'animations {', '    slowdown %.2f' % (g('slowdown') / 100), '}']
    if g('radius_on'):
        L += ['window-rule {', '    geometry-corner-radius %d' % g('radius'), '    clip-to-geometry true', '}']
    return '\n'.join(L) + '\n'


def niri_set(key, value):
    """Store the value, regenerate desk-appearance.kdl, validate with niri; roll everything back on failure."""
    old_prefs = json_get(NIRI_PREFS, key, None)
    old_kdl = NIRI_APP.read_bytes() if NIRI_APP.exists() else None
    old_cfg = NIRI_CFG.read_bytes()
    try:
        json_set(NIRI_PREFS, key, value)
        if NIRI_INCLUDE not in old_cfg.decode():
            snapshot(NIRI_CFG)
            NIRI_CFG.write_text(old_cfg.decode().rstrip('\n') + '\n\n' + NIRI_INCLUDE + '\n')
        tmp = NIRI_APP.with_suffix('.tmp')
        tmp.write_text(_niri_kdl())
        os.replace(tmp, NIRI_APP)
        rc, out, err = run(['niri', 'validate', '-c', str(NIRI_CFG)])
        if rc == 0:
            return True
    except Exception:
        pass
    # roll back
    NIRI_CFG.write_bytes(old_cfg)
    if old_kdl is None:
        NIRI_APP.unlink(missing_ok=True)
    else:
        NIRI_APP.write_bytes(old_kdl)
    if old_prefs is None:
        try:
            d = json.loads(NIRI_PREFS.read_text())
            d.pop(key, None)
            NIRI_PREFS.write_text(json.dumps(d))
        except (OSError, ValueError):
            pass
    else:
        json_set(NIRI_PREFS, key, old_prefs)
    return False


ANIM_LABELS = {'gentle': '柔和', 'pop-drop': '弹性', 'trial-original': '原版', 'original': '原版'}


def niri_presets():
    """Preset name -> file, from every *.kdl next to active.kdl (so users can drop in their own)."""
    d = NIRI_DIR / 'animation-presets'
    return {p.stem: p.name for p in sorted(d.glob('*.kdl')) if p.name != 'active.kdl' and 'before' not in p.stem} if d.is_dir() else {}


def niri_anim_get():
    try:
        cur = (NIRI_DIR / 'animation-presets/active.kdl').read_bytes()
    except OSError:
        return ''
    for k, f in niri_presets().items():
        try:
            if (NIRI_DIR / 'animation-presets' / f).read_bytes() == cur:
                return k
        except OSError:
            pass
    return 'custom'


def niri_anim_set(name):
    active = NIRI_DIR / 'animation-presets/active.kdl'
    src = NIRI_DIR / 'animation-presets' / niri_presets().get(name, '')
    if not src.is_file():
        return False
    old = active.read_bytes()
    tmp = active.with_suffix('.tmp')
    tmp.write_bytes(src.read_bytes())
    os.replace(tmp, active)
    rc, _, _ = run(['niri', 'validate', '-c', str(NIRI_CFG)])
    if rc != 0:
        active.write_bytes(old)
        return False
    return True

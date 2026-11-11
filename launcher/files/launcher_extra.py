#!/usr/bin/env python3
"""Extra launcher data sources: clipboard history (";"), window switcher ("@"), usage ranking.
  clip-add            stdin = clipboard text (called by `wl-paste --watch`)
  clip query [words]  JSON lines, newest first
  win query [words]   JSON lines from niri windows
  win focus ID        focus a niri window
  use KEY             record one use of KEY (app:<desktop id> / file:<path> / win:<app_id>)
"""
import glob, json, os, sqlite3, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
STATE = HOME / '.local/state/launcher-files'
CLIP = STATE / 'clip.db'
USAGE = STATE / 'usage.json'
TABLE_JS = HOME / '.local/share/codex-iris-launcher/source/modules/common/functions/pinyin_table.js'
sys.path.insert(0, str(Path(__file__).parent))
import launcher_files as lf  # noqa: E402

MAX_CLIPS, MAX_LEN = 1000, 20000


def py_keys(text):
    if not lf.CJK.search(text):
        return '', ''
    return lf.pinyin_keys(text[:200], lf.pinyin_table())


def clip_db():
    STATE.mkdir(parents=True, exist_ok=True)
    new = not CLIP.exists()
    con = sqlite3.connect(CLIP)
    if new:
        os.chmod(CLIP, 0o600)                      # clipboard text can be private
    con.execute('CREATE TABLE IF NOT EXISTS clips(id INTEGER PRIMARY KEY, text TEXT UNIQUE, ts REAL, tl TEXT, pf TEXT, pi TEXT)')
    return con


def clip_add():
    types = subprocess.run(['wl-paste', '--list-types'], capture_output=True, text=True).stdout
    if 'passwordManagerHint' in types:             # password managers mark secrets: never store them
        return
    text = sys.stdin.buffer.read().decode('utf-8', 'replace').strip()
    if not text or len(text) > MAX_LEN:
        return
    pf, pi = py_keys(text)
    con = clip_db()
    con.execute('DELETE FROM clips WHERE text=?', (text,))
    con.execute('INSERT INTO clips(text,ts,tl,pf,pi) VALUES(?,?,?,?,?)', (text, time.time(), text[:400].lower(), pf, pi))
    con.execute('DELETE FROM clips WHERE id NOT IN (SELECT id FROM clips ORDER BY ts DESC LIMIT ?)', (MAX_CLIPS,))
    con.commit()


def match(toks, *fields):
    return all(any(t in f for f in fields if f) for t in toks)


def clip_query(words):
    if not CLIP.exists():
        return
    toks = [w.lower() for w in words if w.strip()]
    con = sqlite3.connect(f'file:{CLIP}?mode=ro', uri=True)
    n = 0
    for text, ts, tl, pf, pi in con.execute('SELECT text,ts,tl,pf,pi FROM clips ORDER BY ts DESC'):
        if toks and not match(toks, tl, pf, pi):
            continue
        line = ' '.join(text.split())
        print(json.dumps({'text': text, 'name': line[:120], 'ts': ts, 'lines': text.count('\n') + 1,
                          'chars': len(text)}, ensure_ascii=False))
        n += 1
        if n >= 40:
            break


def niri(*args):
    env = dict(os.environ)
    if not env.get('NIRI_SOCKET'):
        socks = glob.glob(f"/run/user/{os.getuid()}/niri*.sock")
        if socks:
            env['NIRI_SOCKET'] = socks[0]
    return subprocess.run(['niri', 'msg', *args], capture_output=True, text=True, env=env, timeout=3)


def win_query(words):
    toks = [w.lower() for w in words if w.strip()]
    wins = json.loads(niri('--json', 'windows').stdout or '[]')
    try:
        wss = {w['id']: w for w in json.loads(niri('--json', 'workspaces').stdout or '[]')}
    except Exception:
        wss = {}
    use = load_usage()
    rows = []
    for w in wins:
        title, app = w.get('title') or '', w.get('app_id') or ''
        pf, pi = py_keys(title)
        if toks and not match(toks, title.lower(), app.lower(), pf, pi):
            continue
        ws = wss.get(w.get('workspace_id'), {})
        ft = (w.get('focus_timestamp') or {})
        focus = ft.get('secs', 0) + ft.get('nanos', 0) / 1e9
        rows.append((-(focus + use.get('win:' + app, {}).get('n', 0)), {
            'id': w['id'], 'title': title or app, 'app': app,
            'ws': ws.get('name') or ws.get('idx') or w.get('workspace_id'), 'focused': bool(w.get('is_focused'))}))
    rows.sort(key=lambda r: r[0])
    for _, r in rows:
        print(json.dumps(r, ensure_ascii=False))


def load_usage():
    try:
        return json.loads(USAGE.read_text())
    except Exception:
        return {}


def record(key):
    STATE.mkdir(parents=True, exist_ok=True)
    d = load_usage()
    e = d.get(key, {'n': 0, 't': 0})
    e['n'] = min(e['n'] + 1, 500)
    e['t'] = time.time()
    d[key] = e
    if len(d) > 3000:                               # drop the stalest
        for k, _ in sorted(d.items(), key=lambda kv: kv[1]['t'])[:500]:
            del d[k]
    tmp = USAGE.with_suffix('.tmp')
    tmp.write_text(json.dumps(d))
    os.replace(tmp, USAGE)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'clip-add':
        clip_add()
    elif a[0] == 'clip':
        clip_query(a[2:])
    elif a[0] == 'win' and a[1] == 'query':
        win_query(a[2:])
    elif a[0] == 'win' and a[1] == 'focus':
        niri('action', 'focus-window', '--id', a[2])
    elif a[0] == 'use':
        record(a[1])

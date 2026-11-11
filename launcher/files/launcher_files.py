#!/usr/bin/env python3
"""File index + query for the launcher's file mode.

  launcher_files.py index                 rebuild ~/.local/state/launcher-files/index.db (run by a systemd timer)
  launcher_files.py query [text ...]      print up to 30 matches as JSON lines; no text = recently modified files

Names are matched as typed, and Chinese names also by full pinyin and by pinyin initials ("baogao" / "bg" find 报告.docx).
"""
import json
import math
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

HOME = Path.home()
CONF = HOME / '.config/launcher-files/config.json'
DB = HOME / '.local/state/launcher-files/index.db'
TABLE_JS = HOME / '.local/share/codex-iris-launcher/source/modules/common/functions/pinyin_table.js'
CJK = re.compile(r'[一-鿿]')

ICONS = {
    'image-x-generic': {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'avif', 'heic', 'tif', 'tiff'},
    'video-x-generic': {'mp4', 'mkv', 'webm', 'mov', 'avi', 'flv', 'm4v'},
    'audio-x-generic': {'mp3', 'flac', 'wav', 'ogg', 'm4a', 'aac', 'opus'},
    'application-pdf': {'pdf'},
    'x-office-document': {'doc', 'docx', 'odt', 'rtf', 'pages'},
    'x-office-spreadsheet': {'xls', 'xlsx', 'ods', 'csv', 'numbers'},
    'x-office-presentation': {'ppt', 'pptx', 'odp', 'key'},
    'package-x-generic': {'zip', 'rar', '7z', 'tar', 'gz', 'xz', 'bz2', 'zst'},
    'text-x-script': {'py', 'sh', 'js', 'ts', 'rs', 'go', 'c', 'cpp', 'h', 'lua', 'luau', 'qml', 'kdl', 'toml', 'json', 'yaml', 'yml'},
    'text-x-generic': {'txt', 'md', 'log', 'conf', 'ini'},
}
EXT_ICON = {e: icon for icon, exts in ICONS.items() for e in exts}


def load_config():
    try:
        c = json.loads(CONF.read_text())
    except (OSError, ValueError):
        c = {}
    ex = lambda p: os.path.expanduser(p)
    return {
        'roots': [ex(p) for p in c.get('roots', ['~'])],
        'hidden_ok': set(c.get('include_hidden_dirs', ['.config'])),
        'exclude_names': set(c.get('exclude_dir_names', ['.git', 'node_modules'])),
        'exclude_paths': tuple(ex(p).rstrip('/') for p in c.get('exclude_paths', [])),
        'max_files': int(c.get('max_files', 600000)),
    }


def pinyin_table():
    m = re.search(r'var TABLE = (\{.*\});', TABLE_JS.read_text(), re.S)
    return json.loads(m.group(1)) if m else {}


def pinyin_keys(name, table):
    full, init = [], []
    for ch in name:
        py = table.get(ch)
        if py:
            full.append(py)
            init.append(py[0])
        elif ch.isalnum():
            full.append(ch.lower())
            init.append(ch.lower())
    return ''.join(full), ''.join(init)


def build():
    cfg = load_config()
    table = pinyin_table()
    DB.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB.with_suffix('.tmp')
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute('CREATE TABLE files (path TEXT, name TEXT, dir TEXT, nl TEXT, pf TEXT, pi TEXT, mtime INTEGER, isdir INTEGER)')
    rows, n = [], 0

    def walk(top, depth=0):
        nonlocal n
        try:
            it = os.scandir(top)
        except OSError:
            return
        with it:
            for e in it:
                if n >= cfg['max_files']:
                    return
                name = e.name
                is_hidden = name.startswith('.')
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    if name in cfg['exclude_names'] or e.path in cfg['exclude_paths']:
                        continue
                    if is_hidden and not (depth == 0 and name in cfg['hidden_ok']):
                        continue
                elif is_hidden and depth == 0:
                    continue                      # dotfiles right in $HOME are noise
                elif e.is_symlink() and not e.is_file():
                    continue
                try:
                    mt = int(e.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    mt = 0
                pf = pi = ''
                if CJK.search(name):
                    pf, pi = pinyin_keys(name, table)
                rows.append((e.path, name, top, name.lower(), pf, pi, mt, 1 if is_dir else 0))
                n += 1
                if len(rows) >= 20000:
                    con.executemany('INSERT INTO files VALUES (?,?,?,?,?,?,?,?)', rows)
                    rows.clear()
                if is_dir:
                    walk(e.path, depth + 1)

    for root in cfg['roots']:
        walk(root.rstrip('/'))
    con.executemany('INSERT INTO files VALUES (?,?,?,?,?,?,?,?)', rows)
    con.execute('CREATE INDEX idx_mtime ON files(mtime DESC)')
    con.commit()
    con.close()
    os.replace(tmp, DB)
    print('indexed', n, 'entries')


def icon_for(name, is_dir):
    if is_dir:
        return 'folder'
    return EXT_ICON.get(name.rsplit('.', 1)[-1].lower() if '.' in name else '', 'text-x-generic')


def query(words):
    if not DB.exists():
        return
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    toks = [w.lower() for w in words if w.strip()]
    if not toks:
        cur = con.execute('SELECT path,name,dir,isdir,mtime FROM files WHERE isdir=0 ORDER BY mtime DESC LIMIT 800')
        skip_ext = {'log', 'sqlite', 'sqlite3', 'db', 'tmp', 'lock', 'pid', 'sock', 'journal', 'wal', 'shm'}
        rows = []
        for r in cur:                       # "recent" should mean documents, not app data
            ext = r[1].rsplit('.', 1)[-1].lower() if '.' in r[1] else ''
            if ext in skip_ext or '/.config/' in r[0] or '/data/logs/' in r[0] or '/.' in r[0][len(str(HOME)):]:
                continue
            rows.append((r, 0))
            if len(rows) >= 30:
                break
    else:
        where, args = [], []
        for t in toks:
            like = '%' + t.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            where.append("(nl LIKE ? ESCAPE '\\' OR pf LIKE ? ESCAPE '\\' OR pi LIKE ? ESCAPE '\\')")
            args += [like, like, like]
        cur = con.execute('SELECT path,name,dir,isdir,mtime,nl,pf,pi FROM files WHERE ' + ' AND '.join(where) +
                          ' ORDER BY mtime DESC LIMIT 600', args)
        rows = []
        now = time.time()
        try:
            use = json.loads((DB.parent / 'usage.json').read_text())
        except Exception:
            use = {}
        for path, name, d, isdir, mt, nl, pf, pi in cur:
            score = 0.0
            for t in toks:
                if nl.startswith(t):
                    score += 3
                elif t in nl:
                    score += 2
                elif pf.startswith(t) or pi.startswith(t):
                    score += 2.2
                elif t in pf or t in pi:
                    score += 1.2
            score += 1.5 / (1 + (now - mt) / 86400 / 30)         # recent files first
            score -= .5 if isdir else 0                          # slight preference for files
            score -= len(name) / 400
            u = use.get('file:' + path)
            if u:
                score += min(2.5, math.log1p(u['n']) * 0.8)       # files you open often rise
            rows.append(((path, name, d, isdir, mt), score))
        rows.sort(key=lambda r: -r[1])
        rows = rows[:30]
    home = str(HOME)
    for (path, name, d, isdir, mt), _ in rows:
        print(json.dumps({'path': path, 'name': name, 'dir': ('~' + d[len(home):]) if d.startswith(home) else d,
                          'isdir': bool(isdir), 'icon': icon_for(name, isdir)}, ensure_ascii=False))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'query'
    if cmd == 'index':
        build()
    else:
        query(sys.argv[2:])

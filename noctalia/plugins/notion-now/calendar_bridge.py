#!/usr/bin/env python3
"""Read-only calendar bridge; credentials stay in private local files."""
import argparse
import datetime as dt
import fcntl
import html
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'notion-now'
STATE_DIR = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'notion-now'
CONFIG = CONFIG_DIR / 'config.json'
CACHE = STATE_DIR / 'events.json'
NOTION_VERSION = '2025-09-03'


class CalendarError(Exception):
    pass


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default if default is not None else {}


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False)
    tmp.chmod(0o600)
    tmp.replace(path)


def request_json(url, headers=None, body=None, form=False):
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    try:
        if url.startswith('https://api.notion.com/'):
            time.sleep(0.35)
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # Never log response bodies: providers may include credentials or private text.
        if e.code == 401:
            raise CalendarError('授权失效，请重新连接账号') from None
        if e.code == 403:
            raise CalendarError('读取权限不足，请检查日历权限及 API 是否启用') from None
        if e.code == 404:
            raise CalendarError('找不到日历或数据库，请检查链接和共享权限') from None
        if e.code == 429:
            raise CalendarError('请求过于频繁，将在下次同步重试') from None
        raise CalendarError('服务返回错误（HTTP %s）' % e.code) from None
    except (OSError, ValueError):
        raise CalendarError('网络连接失败或服务响应异常') from None


def paged(url, headers, key='items', body=None):
    result = []
    cursor = None
    while True:
        if body is None:
            target = url + (('&' if '?' in url else '?') + urllib.parse.urlencode({'pageToken': cursor}) if cursor else '')
            page = request_json(target, headers)
            cursor = page.get('nextPageToken')
        else:
            payload = dict(body)
            if cursor:
                payload['start_cursor'] = cursor
            page = request_json(url, headers, payload)
            cursor = page.get('next_cursor') if page.get('has_more') else None
        result.extend(page.get(key, []))
        if not cursor:
            return result


def parse_time(value, timezone, hint=None):
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(hint) if hint else timezone)
    return parsed.timestamp()


def notion_title(items):
    return ''.join(x.get('plain_text', x.get('text', {}).get('content', '')) for x in items)


def normalize_notion(page, date_property, name, timezone):
    if page.get('archived') or page.get('in_trash'):
        return None
    props = page.get('properties', {})
    date = props.get(date_property, {}).get('date')
    if not date or not date.get('start'):
        return None
    title = next((notion_title(p.get('title', [])) for p in props.values() if p.get('type') == 'title'), '')
    all_day = len(date['start']) == 10
    start = parse_time(date['start'], timezone, date.get('time_zone'))
    point = not all_day and not date.get('end')
    end = parse_time(date.get('end'), timezone, date.get('time_zone'))
    if all_day:
        # Notion date ranges include the final date.
        last = dt.date.fromisoformat(date.get('end') or date['start'])
        end = dt.datetime.combine(last + dt.timedelta(days=1), dt.time(), timezone).timestamp()
    elif point:
        end = start
    if end is None or end < start:
        return None
    return {'id': 'notion:' + page['id'], 'provider': 'notion', 'calendar': name,
            'title': title or '未命名活动', 'start': start, 'end': end, 'all_day': all_day,
            'point': point, 'url': page.get('url', '')}


def resolve_database_id(value):
    match = re.search(r'([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:[?/#]|$)', value, re.I)
    if not match:
        raise CalendarError('数据库链接或 ID 格式不正确')
    return match.group(1)


def notion_events(config, timezone, begin, finish):
    notion = config.get('notion', {})
    if not notion.get('token'):
        raise CalendarError('尚未连接 Notion 数据库')
    headers = {'Authorization': 'Bearer ' + notion['token'], 'Notion-Version': NOTION_VERSION}
    sources = notion.get('sources', [])
    if not sources:
        # Only databases explicitly shared with this integration can be discovered.
        found = paged('https://api.notion.com/v1/search', headers, 'results',
                      {'filter': {'value': 'data_source', 'property': 'object'}, 'page_size': 100})
        sources = [{'id': x['id'], 'name': notion_title(x.get('title', []))} for x in found]
    if not sources:
        raise CalendarError('未找到共享数据库，请在 Notion 数据库中添加此连接')
    events = []
    for source in sources:
        ident = source['id']
        if source.get('database'):
            db = request_json('https://api.notion.com/v1/databases/' + ident, headers)
            source_ids = [x['id'] for x in db.get('data_sources', [])]
        else:
            source_ids = [ident]
        for source_id in source_ids:
            meta = request_json('https://api.notion.com/v1/data_sources/' + source_id, headers)
            date_keys = [k for k, p in meta.get('properties', {}).items() if p.get('type') == 'date']
            date_key = source.get('date_property') or (date_keys[0] if len(date_keys) == 1 else None)
            if not date_keys:
                continue
            if not date_key:
                raise CalendarError('数据库存在多个日期字段，请在连接设置中指定日期字段名称')
            if date_key not in date_keys:
                raise CalendarError('指定的日期字段不存在')
            name = source.get('name') or notion_title(meta.get('title', [])) or 'Notion'
            # No lower start bound: include long-running ranges that began before today.
            pages = paged('https://api.notion.com/v1/data_sources/' + source_id + '/query', headers,
                'results', {'page_size': 100, 'filter': {'property': date_key,
                'date': {'on_or_before': finish.isoformat()}}})
            for page in pages:
                event = normalize_notion(page, date_key, name, timezone)
                if event and overlaps(event, begin.timestamp(), finish.timestamp()):
                    events.append(event)
    return events


def overlaps(event, begin, finish):
    return (begin <= event['start'] < finish) if event.get('point') else (event['start'] < finish and event['end'] > begin)


def select_events(events, now):
    active = sorted((e for e in events if not e.get('all_day') and not e.get('point')
                     and e['start'] <= now < e['end']), key=lambda e: (e['end'], e['start'], e['id']))
    upcoming = sorted((e for e in events if not e.get('all_day') and e['start'] > now), key=lambda e: (e['start'], e['id']))
    return active, upcoming


def sync():
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE_DIR.chmod(0o700)
    with (STATE_DIR / 'sync.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        config = read_json(CONFIG)
        timezone = ZoneInfo(config.get('timezone', 'Asia/Shanghai'))
        now = dt.datetime.now(timezone)
        begin = now.replace(hour=0, minute=0, second=0, microsecond=0)
        finish = begin + dt.timedelta(days=2)
        previous = read_json(CACHE)
        events, statuses = [], {}
        for provider, fetch in [('notion', notion_events)]:
            connected = bool(config.get(provider, {}))
            try:
                if not connected:
                    raise CalendarError('尚未连接 ' + 'Notion 数据库')
                fetched = fetch(config, timezone, begin, finish)
                statuses[provider] = {'ok': True, 'connected': True, 'updated': time.time(), 'message': '已同步'}
                for event in fetched:
                    event['stale'] = False
                events.extend(fetched)
            except (CalendarError, KeyError, ValueError) as error:
                message = str(error) if isinstance(error, CalendarError) else '服务数据格式异常，请检查设置'
                statuses[provider] = {'ok': False, 'connected': connected, 'message': message,
                    'updated': previous.get('sources', {}).get(provider, {}).get('updated', 0)}
                if connected:
                    for event in previous.get('events', []):
                        if event['provider'] == provider and overlaps(event, begin.timestamp(), finish.timestamp()):
                            events.append(dict(event, stale=True))
        events = sorted({e['id']: e for e in events}.values(), key=lambda e: (e['start'], e['id']))
        save_json(CACHE, {'updated': time.time(), 'timezone': str(timezone), 'sources': statuses, 'events': events})


def setup_page(message='', csrf=''):
    config = read_json(CONFIG)
    source_status = read_json(CACHE).get('sources', {})
    status = 'Notion：' + source_status.get('notion', {}).get('message', '尚未连接')
    notion = config.get('notion', {})
    source_text = '\n'.join(x['id'] + (' | ' + x['date_property'] if x.get('date_property') else '') for x in notion.get('sources', []))
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Notion Now · 日历连接</title><style>
*{box-sizing:border-box}body{margin:0;background:#151714;color:#e5e9df;font:16px system-ui;line-height:1.65}
main{max-width:780px;margin:56px auto;padding:0 24px}h1{font-size:32px;margin-bottom:8px}h2{font-size:21px}
.muted,small{color:#a6ada1}.card{border:1px solid #394034;background:#20241d;border-radius:20px;padding:26px;margin:24px 0}
label{display:block;margin:14px 0 6px}input,textarea{width:100%;background:#12150f;color:#e5e9df;border:1px solid #424b3c;border-radius:10px;padding:12px;font:14px monospace}
button{border:0;border-radius:10px;padding:12px 18px;background:#c1d6a6;color:#17200e;font-weight:700;font-size:15px;cursor:pointer}
a{color:#c1d6a6}.note{color:#d5dda4;padding:14px 0}.row{display:flex;gap:12px;align-items:center}code{color:#d5dda4}
</style><main><h1>日历，此刻</h1><div class="muted">连接 Notion 数据库，让顶栏显示现在的安排。</div>
<div class="note">''' + html.escape(message or status or '插件已安装，等待连接日历。') + '''</div>
<section class="card"><h2>Notion 数据库</h2><p>创建仅有读取内容权限的内部集成，然后在需要显示的数据库中，通过「连接」添加这个集成。</p>
<p><a href="https://www.notion.so/profile/integrations" target="_blank" rel="noreferrer">打开 Notion 集成管理 ↗</a></p>
<form method="post" action="/notion"><input type="hidden" name="csrf" value="''' + csrf + '''">
<label for="token">集成密钥</label><input id="token" type="password" name="token" autocomplete="off" placeholder="''' + ('已保存；留空保留现有密钥' if notion.get('token') else '粘贴 Notion integration secret') + '''">
<label for="databases">数据库链接或 ID（每行一个，可留空自动查找已共享数据库）</label>
<textarea id="databases" name="databases" rows="3" placeholder="数据库链接 | 日期字段名称（只有一个日期字段时可省略）">''' + html.escape(source_text) + '''</textarea>
<small>如有多个日期字段，请写成：数据库链接 | 日期。选择与 Notion Calendar 中相同的日期字段。</small>
<p><button>保存并同步 Notion</button></p></form></section>
<p class="muted">密钥只保存在本机权限为 600 的配置文件中。插件每两分钟同步，在活动起止时间自动切换。
全天活动不会占用「正在进行」；没有结束时间的任务只显示时间点，不推测持续时长。</p></main></html>'''


def serve(open_browser=False):
    csrf = secrets.token_urlsafe(32)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, message='', status=200):
            body = setup_page(message, csrf).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host') == '127.0.0.1:18743'

        def do_GET(self):
            if not self.valid_host():
                self.send_error(403)
                return
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == '/':
                self.reply()
            else:
                self.send_error(404)

        def do_POST(self):
            if not self.valid_host() or self.headers.get('Origin', 'http://127.0.0.1:18743') != 'http://127.0.0.1:18743':
                self.send_error(403)
                return
            length = int(self.headers.get('Content-Length', 0))
            if length > 65536:
                self.send_error(413)
                return
            form = urllib.parse.parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            value = lambda key: form.get(key, [''])[0].strip()
            if not secrets.compare_digest(value('csrf'), csrf):
                self.send_error(403)
                return
            config = read_json(CONFIG)
            config.setdefault('timezone', 'Asia/Shanghai')
            try:
                if self.path == '/notion':
                    token = value('token') or config.get('notion', {}).get('token')
                    if not token:
                        raise CalendarError('请先填入 Notion 集成密钥')
                    sources = []
                    for line in value('databases').splitlines():
                        if not line.strip():
                            continue
                        fields = line.split('|', 1)
                        sources.append({'id': resolve_database_id(fields[0].strip()), 'database': True,
                            'date_property': fields[1].strip() if len(fields) > 1 else ''})
                    config['notion'] = {'token': token, 'sources': sources}
                    save_json(CONFIG, config)
                    threading.Thread(target=sync, daemon=True).start()
                    self.reply('Notion 设置已保存，正在检查权限并同步。稍后刷新查看结果。')
                else:
                    self.send_error(404)
            except (CalendarError, ValueError):
                self.reply('设置格式不正确，请检查密钥和数据库链接。', 400)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 18743), Handler)
    if open_browser:
        import webbrowser
        webbrowser.open('http://127.0.0.1:18743')
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['sync', 'serve', 'setup'])
    args = parser.parse_args()
    if args.action == 'sync':
        sync()
    elif args.action == 'serve':
        serve()
    else:
        import subprocess
        subprocess.run(['systemctl', '--user', 'start', 'notion-now-setup.service'], check=True)
        subprocess.run(['xdg-open', 'http://127.0.0.1:18743'], check=True)

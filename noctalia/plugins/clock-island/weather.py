"""Current weather, read from Noctalia's own cache (~/.cache/noctalia/weather.json); no network access here."""
import json
import time
from pathlib import Path

FILE = Path.home() / '.cache/noctalia/weather.json'
NAMES = {'clear': '晴', 'partly': '多云', 'cloud': '阴', 'fog': '雾', 'drizzle': '小雨', 'rain': '雨', 'snow': '雪', 'storm': '雷雨'}


def cond_of(code):
    if code in (0, 1):
        return 'clear'
    if code == 2:
        return 'partly'
    if code == 3:
        return 'cloud'
    if code in (45, 48):
        return 'fog'
    if code in (51, 53, 55, 56, 57):
        return 'drizzle'
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return 'rain'
    if code in (71, 73, 75, 77, 85, 86):
        return 'snow'
    if code in (95, 96, 99):
        return 'storm'
    return 'cloud'


def read(max_age=6 * 3600):
    try:
        snap = json.loads(FILE.read_text())['snapshot']
        cur = snap['current']
        if time.time() - float(snap.get('fetched_at', 0)) > max_age:
            return None
        code = int(cur['weather_code'])
        cond = cond_of(code)
        return dict(code=code, cond=cond, name=NAMES[cond], temp=float(cur['temperature_c']))
    except (OSError, ValueError, KeyError, TypeError):
        return None

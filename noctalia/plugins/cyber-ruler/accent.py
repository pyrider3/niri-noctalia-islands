"""Accent colour derived from the current Noctalia wallpaper (cached, no subprocess)."""
import colorsys, os, time
from pathlib import Path

DEFAULT = (.53, .77, .98)
SETTINGS = Path(os.environ.get('NOCTALIA_SETTINGS', Path.home() / '.local/state/noctalia/settings.toml'))
_cache = {}

def wallpaper_path(output, settings=None):
    import tomllib
    try:
        data = tomllib.loads((settings or SETTINGS).read_text())
    except (OSError, ValueError):
        return None
    wp = data.get('wallpaper', {})
    for entry in ((wp.get('monitors') or {}).get(output), wp.get('default'), wp.get('last')):
        if isinstance(entry, dict) and entry.get('path'):
            return entry['path']
    return None

def dominant(path):
    """Most prominent *vivid* hue of an image, lifted so it stays readable on dark glass."""
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert('RGB'); img.thumbnail((64, 64))
        pixels = list(img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata())
    bins = [[0., 0., 0., 0.] for _ in range(12)]          # weight, r, g, b
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
        w = s*s*v
        if w <= .002: continue
        slot = bins[int(h*12) % 12]
        slot[0] += w; slot[1] += r*w; slot[2] += g*w; slot[3] += b*w
    best = max(bins, key=lambda s: s[0])
    if best[0] <= 0: return DEFAULT
    r, g, b = (best[i]/best[0]/255 for i in (1, 2, 3))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return colorsys.hsv_to_rgb(h, max(.42, min(.85, s)), max(.82, v))

def wallpaper_accent(output, now=None, settings=None):
    now = time.monotonic() if now is None else now
    hit = _cache.get(output)
    if hit and now - hit[0] < 5: return hit[1]
    path = wallpaper_path(output, settings)
    try: stamp = (path, os.stat(path).st_mtime_ns) if path else None
    except OSError: stamp = None
    if hit and hit[2] == stamp:
        _cache[output] = (now, hit[1], stamp); return hit[1]
    try: rgb = dominant(path) if stamp else DEFAULT
    except Exception: rgb = DEFAULT
    _cache[output] = (now, rgb, stamp)
    return rgb

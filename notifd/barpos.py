"""Find a bar widget on screen by looking for the marker pixels its canvas draws (no API gives widget positions)."""
import io
import json
import subprocess

import cairo



def screen_info():
    """(output name, logical width, scale) of the bar's monitor."""
    try:
        out = json.loads(subprocess.check_output(['niri', 'msg', '--json', 'outputs'], timeout=2).decode())
        items = out.items() if isinstance(out, dict) else [(o.get('name'), o) for o in out]
        for name, o in items:
            lg = o.get('logical') or {}
            if lg.get('width'):
                return name, float(lg['width']), float(lg.get('scale') or 1.0)
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError, TypeError):
        pass
    return None, 1755.0, 1.75


def find_marker(rgb, min_run=3, vchecks=(2, 4)):
    """Find a solid block of exactly this colour in a screenshot of the bar.

    The bar canvases draw part of their own icon in a colour that differs from the icon's visible colour by 1/255 in
    one channel, so the marker is invisible but exact. Returns (left, right, screen logical width) in layout px.
    """
    name, lw, _ = screen_info()
    px = bytes([rgb[2], rgb[1], rgb[0], 255])
    pattern = px * min_run
    cmd = ['grim'] + (['-o', name] if name else []) + ['-']
    try:
        png = subprocess.check_output(cmd, timeout=3, stderr=subprocess.DEVNULL)
        surf = cairo.ImageSurface.create_from_png(io.BytesIO(png))
    except (OSError, subprocess.SubprocessError, cairo.Error):
        return None
    w, stride = surf.get_width(), surf.get_stride()
    scale = w / lw
    data = bytes(surf.get_data())
    rows = int(70 * scale)
    for y in range(0, rows):
        row = data[y * stride:y * stride + w * 4]
        at = row.find(pattern)
        while at >= 0:
            if at % 4 == 0:
                ok = all(y + dy < rows and data[(y + dy) * stride + at:(y + dy) * stride + at + 4 * min_run] == pattern
                         for dy in vchecks)
                if ok:
                    end = at + 4 * min_run
                    while end + 4 <= len(row) and row[end:end + 4] == px:
                        end += 4
                    return at / 4 / scale, end / 4 / scale, lw
            at = row.find(pattern, at + 1)
    return None

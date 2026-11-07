import unittest, tempfile, os
from pathlib import Path
from ruler import Ruler, pixel_bytes, HEADING_THEMES
import accent

def cols(base, apps):
    return [dict(key=[0, i+1], floating=False, windows=[dict(id=base+i, app=a, row=1)]) for i, a in enumerate(apps)]

def workspaces(active=2):
    spec = [(1, ['KITTY', 'FIREFOX'], 10), (2, ['TERMINAL', 'CODE', 'FILES'], 21), (3, [], None), (4, ['CHROMIUM'], 40)]
    return [dict(id=i, idx=i, is_active=i == active, count=len(a), app='X', columns=cols(i*10, a), focused_window=f) for i, a, f in spec]

class NewThemeTests(unittest.TestCase):
    THEMES = ('glass', 'pill', 'merged', 'stars', 'pearls', 'mercury', 'barrel', 'neon')
    def make(self, theme, **extra):
        r = Ruler(); r.configure(dict(theme=theme, width=300, **extra)); r.set_workspaces(workspaces(), 0); return r
    def test_registered_and_independent(self):
        self.assertTrue(set(self.THEMES) <= set(HEADING_THEMES))
        r = self.make('pill'); self.assertIs(r.heading, r.headings['pill'])
    def test_paint_size_transparency_and_content(self):
        for theme in self.THEMES:
            r = self.make(theme); s = r.paint(0); raw = pixel_bytes(s, True)
            self.assertEqual((s.get_width(), s.get_height()), (600, 84))
            self.assertEqual(raw[3], 0); self.assertEqual(raw[-1], 0)
            self.assertGreater(max(raw[3::4]), 200, theme)
    def test_no_crash_through_workspace_and_focus_changes(self):
        for theme in self.THEMES:
            r = self.make(theme); r.paint(0)
            r.set_workspaces(workspaces(active=1), 1)
            for now in (1.0, 1.05, 1.15, 1.3, 1.6): r.paint(now)
            ws = workspaces(active=4); r.set_workspaces(ws, 2); r.paint(2.1)
            r.set_workspaces([], 3); r.paint(3)
            r.configure(dict(theme=theme, width=180, show_windows=False)); r.set_workspaces(workspaces(), 4); r.paint(4)
    def test_merged_click_targets_windows_across_workspaces(self):
        r = self.make('merged'); h = r.heading; r.paint(5)
        xs = h.item_x
        k = next(i for i, it in enumerate(h.items) if it['window'] == 10)
        act = h.window_action(r, dict(kind='window-click', value=xs[k]/r.width), 5)
        self.assertEqual(act, {'Action': {'FocusWindow': {'id': 10}}})
        k = next(i for i, it in enumerate(h.items) if it['window'] is None)
        act = h.window_action(r, dict(kind='window-click', value=xs[k]/r.width), 5)
        self.assertEqual(act, {'Action': {'FocusWorkspace': {'reference': {'Id': 3}}}})
        self.assertEqual(h.window_action(r, dict(kind='window-step', value=1), 5), {'Action': {'FocusWindow': {'id': 22}}})
    def test_merged_focus_is_centred(self):
        r = self.make('merged'); r.paint(5); h = r.heading
        k = next(i for i, it in enumerate(h.items) if it['window'] == 21)
        self.assertAlmostEqual(h.item_x[k], r.width/2, delta=.01)
    def test_pill_click_uses_inherited_window_mapping(self):
        r = self.make('pill'); r.paint(5)
        x = r.heading.point(0, r.width, 5, True)
        self.assertEqual(r.heading.window_action(r, dict(kind='window-click', value=x/r.width), 5), {'Action': {'FocusWindow': {'id': 20}}})

class AccentTests(unittest.TestCase):
    def test_dominant_prefers_vivid_hue(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'w.png'; im = Image.new('RGB', (32, 32), (20, 20, 20))
            for x in range(20):
                for y in range(32): im.putpixel((x, y), (30, 200, 60))
            im.save(p); r, g, b = accent.dominant(p)
            self.assertGreater(g, r); self.assertGreater(g, b)
    def test_wallpaper_lookup_and_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Path(tmp)/'settings.toml'
            s.write_text('[wallpaper.default]\npath = "/nope.png"\n[wallpaper.monitors.A]\npath = "/mon.png"\n')
            self.assertEqual(accent.wallpaper_path('A', s), '/mon.png')
            self.assertEqual(accent.wallpaper_path('B', s), '/nope.png')
            self.assertEqual(accent.wallpaper_accent('Z-missing', 0, s), accent.DEFAULT)
            self.assertIsNone(accent.wallpaper_path('A', Path(tmp)/'missing.toml'))
    def test_ruler_uses_wallpaper_only_when_asked(self):
        r = Ruler(); r.configure({}); self.assertEqual(r.accent_rgb((1, 0, 0)), (1, 0, 0))
        r.configure(dict(accent_source='wallpaper')); r.output = 'none-such'
        self.assertEqual(len(r.accent_rgb((1, 0, 0), 0)), 3)

if __name__ == '__main__': unittest.main()

"""Pages for the settings island (declarative: rows read current values and apply changes through backend)."""
import threading
from pathlib import Path

import backend as B
from gi.repository import GLib
from ds_ui import Button, Cards, Group, Info, Page, Section, Seg, Step, Switch, Text

NOTION = Path.home() / '.local/state/notion-now/preferences.json'
WALL_DIR = Path.home() / 'Pictures/wall'
IMG_EXT = {'.jpg', '.jpeg', '.png', '.webp'}


def P(plugin):
    return (lambda k, d=None: B.plugin_get(plugin, k, d)), (lambda k, v: B.plugin_set(plugin, k, v))


def page_notifications(app):
    get, set_ = P('local/notifd-bell')
    return Page('通知',
        Section('样式', '新通知和历史通知的外观与出场方式'),
        Group(Seg('通知样式', '切换立即生效', [('card', '深色卡片'), ('frost', '亮色磨砂'), ('island', '灵动岛'), ('capsule', '栏内胶囊'), ('bell', '铃铛摇出')],
                  lambda: get('style', 'card'), lambda v: set_('style', v), 'card')),
        Section('声音', '低优先级通知不响；免打扰时只有紧急通知会响'),
        Group(Switch('通知提示音', None, lambda: get('sound', True), lambda v: set_('sound', v), True),
              Seg('提示音效', '只影响普通通知，紧急通知固定是警告音', [('message', '轻快'), ('message2', '柔和'), ('bell', '铃声'), ('complete', '完成'), ('attention', '提醒')],
                  lambda: get('sound_effect', 'message'), lambda v: set_('sound_effect', v), 'message')))


def page_clock(app):
    get, set_ = P('local/clock-island')
    return Page('时钟',
        Section('时钟', '栏上的动态时钟和点开的日历岛'),
        Group(Switch('栏上显示秒', '日历岛里始终显示秒', lambda: get('show_seconds', False), lambda v: set_('show_seconds', v))),
        Section('番茄钟'),
        Group(Step('专注时长', None, 1, 180, lambda: get('pomo_focus', 25), lambda v: set_('pomo_focus', v), 25, suffix=' 分钟'),
              Step('短休息', None, 1, 60, lambda: get('pomo_short', 5), lambda v: set_('pomo_short', v), 5, suffix=' 分钟'),
              Step('长休息', None, 1, 90, lambda: get('pomo_long', 15), lambda v: set_('pomo_long', v), 15, suffix=' 分钟'),
              Switch('阶段结束后自动开始下一阶段', None, lambda: get('pomo_auto', True), lambda v: set_('pomo_auto', v), True)))


def page_notion(app):
    def get(k, d=None):
        return B.json_get(NOTION, k, d)

    def set_(k, v):
        return B.json_set(NOTION, k, v)
    return Page('日程',
        Section('栏上胶囊', '日程胶囊如何显示当前活动'),
        Group(Seg('活动如何显示', None, [('pinned', '主日程'), ('parallel', '同时显示'), ('rotate', '自动轮播')],
                  lambda: get('display_mode', 'pinned'), lambda v: set_('display_mode', v), 'pinned'),
              Step('同时显示数量', '仅"同时显示"模式', 1, 5, lambda: get('max_visible', 2), lambda v: set_('max_visible', v), 2, suffix=' 项'),
              Step('轮播间隔', '仅"自动轮播"模式', 2, 15, lambda: get('rotate_seconds', 5), lambda v: set_('rotate_seconds', v), 5, suffix=' 秒'),
              Step('标题最多显示', None, 8, 28, lambda: get('title_limit', 18), lambda v: set_('title_limit', v), 18, suffix=' 字'),
              Switch('主题强调色', None, lambda: get('accent_color', False), lambda v: set_('accent_color', v)),
              Switch('活动进度条', None, lambda: get('show_progress', True), lambda v: set_('show_progress', v), True)),
        Section('提醒'),
        Group(Switch('开始前弹出提醒横幅', '日程快开始时，灵动岛自动弹出', lambda: get('island_remind', True), lambda v: set_('island_remind', v), True),
              Step('提前多久', None, 1, 30, lambda: get('island_lead', 5), lambda v: set_('island_lead', v), 5, suffix=' 分钟'),
              Switch('临近结束变色', '剩余时间不足时进度条变橙色', lambda: get('end_warning', True), lambda v: set_('end_warning', v), True),
              Step('结束前多久变色', None, 1, 30, lambda: get('end_warning_minutes', 5), lambda v: set_('end_warning_minutes', v), 5, suffix=' 分钟')))


def page_hub(app):
    get, set_ = P('local/cyber-ruler')
    themes = [('classic', '经典赛博'), ('aviation', '飞行仪表'), ('aviation_spring', '飞行·弹性'), ('glass', '玻璃轨道'), ('pill', '药丸胶囊'),
              ('merged', '合并刻度'), ('stars', '星星'), ('pearls', '珍珠'), ('mercury', '水银'), ('barrel', '桶形'), ('neon', '霓虹'),
              ('islands', '窗口群岛'), ('filmstrip', '桌面底片')]
    return Page('中间刻度尺',
        Section('事件提示', '原版赛博刻度尺的新功能：开启后，这些变化会让刻度尺变形成一个黑色胶囊提示'),
        Group(Switch('事件提示', '麦克风、Wi-Fi、蓝牙、勿扰、大小写与数字锁定、电源模式、切歌', lambda: get('events', False), lambda v: set_('events', v), False),
              Switch('输入法切换提示', '切换中英 / 键盘布局时，在胶囊里弹出当前输入法', lambda: get('event_ime', True), lambda v: set_('event_ime', v), True)),
        Group(Switch('单击展开面板', '仅「合并刻度」主题：点当前窗口胶囊，展开所有工作区与窗口的总览，可点击跳转，底部有浮动、全屏、移动、关闭', lambda: get('panel', False), lambda v: set_('panel', v), False)),
        Section('外观', '栏中间的 niri 工作区与窗口刻度尺'),
        Group(Switch('黑色灵动岛模式', '仅「合并刻度」主题：打开则当前窗口胶囊平时就是黑色；关闭保持白色胶囊。事件提示都会从胶囊里长出黑岛', lambda: get('island', False), lambda v: set_('island', v), False)),
        Group(Seg('主题', None, themes, lambda: get('theme', 'classic'), lambda v: set_('theme', v), 'classic'),
              Step('宽度', None, 180, 520, lambda: get('width', 300), lambda v: set_('width', v), 300, step=20, suffix=' px'),
              Switch('显示窗口刻度', '关闭则只显示工作区', lambda: get('show_windows', True), lambda v: set_('show_windows', v), True),
              Switch('切换扫光动画', None, lambda: get('animate', True), lambda v: set_('animate', v), True)))


OSD_KINDS = [('volume', '音量'), ('brightness', '亮度'), ('wifi', 'Wi-Fi 开关'), ('bluetooth', '蓝牙开关'),
             ('power_profile', '电源模式'), ('caffeine', '防止休眠'), ('nightlight', '夜间模式'), ('dnd', '勿扰'),
             ('lock_keys', '大小写与数字锁定'), ('keyboard_layout', '键盘布局'), ('privacy', '麦克风、摄像头、共享屏幕'), ('media', '切歌（已由刻度尺的岛显示）')]


def page_osd(app):
    rows = [Switch(label, None, (lambda k=k: B.ncfg_get('osd.kinds.' + k, True)), (lambda v, k=k: B.ncfg_set('osd.kinds.' + k, v)), True)
            for k, label in OSD_KINDS]
    return Page('提示弹窗',
        Section('Noctalia 自带弹窗', '音量、亮度等已由状态胶囊、中间刻度尺接管的项目可以在这里关掉'),
        Group(*rows),
        Section('显示时间'),
        Group(Step('弹窗停留', None, 250, 10000, lambda: B.ncfg_get('osd.hide_delay_ms', 1400), lambda v: B.ncfg_set('osd.hide_delay_ms', v), 1400, step=50, suffix=' 毫秒')))


def page_wallpaper(app):
    files = sorted([p for p in WALL_DIR.rglob('*') if p.suffix.lower() in IMG_EXT])[:120] if WALL_DIR.exists() else []
    state = {'cur': B.run(['noctalia', 'msg', 'wallpaper-get'])[1].strip()}
    thumbs = {}

    def getter(path):
        def g():
            if path not in thumbs:
                thumbs[path] = None
                app.load_thumb(path, thumbs)
            return thumbs[path]
        return g

    def pick(key):
        def work():
            B.run(['noctalia', 'msg', 'wallpaper-set', key], 10)
            state['cur'] = key
            app.request_draw()
        threading.Thread(target=work, daemon=True).start()
        state['cur'] = key
        app.toast('壁纸已更换')

    def nav(cmd):
        def go():
            def work():
                B.run(['noctalia', 'msg', cmd])
                state['cur'] = B.run(['noctalia', 'msg', 'wallpaper-get'])[1].strip()
                app.request_draw()
            threading.Thread(target=work, daemon=True).start()
        return go
    cards = Cards([(str(p), p.name, getter(str(p))) for p in files], 3, pick, lambda: state['cur'])
    return Page('壁纸',
        Section('当前壁纸', ''),
        Group(Info(lambda: '当前：' + state['cur'], 44),
              Button('下一张', None, '切换', nav('wallpaper-next')),
              Button('上一张', None, '切换', nav('wallpaper-previous')),
              Button('随机一张', None, '换一张', nav('wallpaper-random'))),
        Section('图库', '~/Pictures/wall'),
        Group(cards, card=False))


def page_we(app):
    items = B.we_list()
    state = {'cur': B.we_current()}
    thumbs = {}

    def getter(path):
        def g():
            if not path:
                return None
            if path not in thumbs:
                thumbs[path] = None
                app.load_thumb(path, thumbs)
            return thumbs[path]
        return g

    def pick(wid):
        title = next((it['title'] for it in items if it['id'] == wid), wid)
        state['cur'] = wid
        app.toast('正在应用：%s' % title[:18])

        def work():
            ok = B.we_apply(wid)
            state['cur'] = B.we_current() if ok else state['cur']
            GLib.idle_add(app.toast, '已应用' if ok else '应用失败，请看日志')
        threading.Thread(target=work, daemon=True).start()

    def pref(key):
        def set_(v):
            B.we_pref_set(key, v)
            cur = B.we_current()
            if cur:
                B.we_apply(cur)
            return True
        return (lambda: B.we_pref(key)), set_

    def stop():
        def work():
            B.we_stop()
            state['cur'] = ''
            GLib.idle_add(app.toast, '动态壁纸已停止（显示静态壁纸）')
        threading.Thread(target=work, daemon=True).start()

    g_scale, s_scale = pref('scaling')
    g_fps, s_fps = pref('fps')
    g_sil, s_sil = pref('silent')
    g_vol, s_vol = pref('volume')
    cards = Cards([(it['id'], '%s · %s' % (it['title'], it['type'] or '?'), getter(it['thumb'])) for it in items], 3, pick,
                  lambda: state['cur'], labels=True)
    return Page('动态壁纸',
        Section('Wallpaper Engine', '点一张就切换；本机 %d 个创意工坊壁纸（eDP-1）' % len(items)),
        Group(cards, card=False),
        Section('播放', '修改后会立即重启当前壁纸'),
        Group(Seg('缩放', None, [('fill', '填充'), ('fit', '适应'), ('stretch', '拉伸'), ('default', '默认')], g_scale, s_scale, 'fill'),
              Seg('帧率上限', '越低越省电', [(15, '15'), (30, '30'), (60, '60')], g_fps, s_fps, 30),
              Switch('静音', None, g_sil, s_sil, False),
              Step('音量', '静音关闭时生效', 0, 100, g_vol, s_vol, 15, step=5, suffix='%'),
              Button('停止动态壁纸', '回到 Noctalia 的静态壁纸', '停止', stop)))


def page_niri(app):
    g = B.niri_get

    def n(key):
        return (lambda: g(key)), (lambda v: B.niri_set(key, v))
    return Page('外观（niri）',
        Section('窗口', '改动写入 ~/.config/niri/desk-appearance.kdl，niri 校验通过才生效，失败自动还原'),
        Group(Step('窗口间距', None, 0, 40, *n('gaps'), 10, suffix=' px'),
              Step('焦点环宽度', None, 0, 40, *n('ring'), 1, fmt=lambda v: '%.1f px' % (v / 10)),
              Switch('统一窗口圆角', '打开后覆盖各应用单独的圆角规则', *n('radius_on'), False),
              Step('圆角半径', None, 0, 40, *n('radius'), 12, suffix=' px')),
        Section('阴影'),
        Group(Switch('窗口阴影', None, *n('shadow'), False),
              Step('柔和度', None, 0, 100, *n('softness'), 50, step=5, suffix=' px'),
              Step('扩散', None, 0, 30, *n('spread'), 0, suffix=' px')),
        Section('背景模糊', '作用于透明窗口和栏'),
        Group(Step('模糊次数', '越高越柔，越耗显卡', 1, 8, *n('passes'), 4),
              Step('模糊半径', None, 1, 20, *n('offset'), 5),
              Step('颗粒', None, 0, 100, *n('noise'), 15, step=5, fmt=lambda v: '%.1f%%' % (v / 10)),
              Step('饱和度', None, 50, 250, *n('saturation'), 125, step=5, suffix='%')),
        Section('动画'),
        Group(Seg('动画预设', '立即生效', [(k, B.ANIM_LABELS.get(k, k)) for k in B.niri_presets()] or [('', '（无预设）')],
                  lambda: B.niri_anim_get(), lambda v: B.niri_anim_set(v), ''),
              Step('整体速度', '100% 为预设原速，数值越大越慢', 25, 400, *n('slowdown'), 100, step=25, suffix='%')))


def page_noctalia(app):
    def c(path, d=None):
        return (lambda: B.ncfg_get(path, d)), (lambda v: B.ncfg_set(path, v))

    def pct(path, d):
        return (lambda: round(float(B.ncfg_get(path, d)) * 100)), (lambda v: B.ncfg_set(path, round(v / 100, 2)))

    def tenth(path, d):
        return (lambda: round(float(B.ncfg_get(path, d)) * 10)), (lambda v: B.ncfg_set(path, round(v / 10, 1)))
    auto = Switch('自动定位', '按网络判断所在城市；填了城市后会自动关闭', *c('location.auto_locate', True), True)

    def set_city(v):
        # a city turns auto-locate off; clearing it turns auto-locate back on
        ok = B.ncfg_set('location.address', v)
        ok = B.ncfg_set('location.auto_locate', not v) and ok
        auto.value = not v
        return ok
    city = Text('城市', '用于天气，如「北京」「上海」或 Shanghai；回车确认', lambda: B.ncfg_get('location.address', ''), set_city, '自动定位')
    return Page('状态栏与 Noctalia',
        Section('状态栏', '改动经 Noctalia 写入并热加载'),
        Group(Switch('胶囊底', '每个组件带一个圆角底', *c('bar.default.capsule', True), True),
              Step('背景不透明度', '0% 为完全透明', 0, 100, *pct('bar.default.background_opacity', 0.0), 0, step=10, suffix='%'),
              Step('两端边距', None, 0, 40, *c('bar.default.margin_ends', 10), 10, suffix=' px'),
              Step('圆角', None, 0, 40, *c('bar.default.radius', 15), 15, suffix=' px'),
              Switch('阴影', None, *c('bar.default.shadow', False), False),
              Switch('凹形边角', None, *c('bar.default.concave_edge_corners', False), False)),
        Section('Noctalia 外壳'),
        Group(Step('圆角缩放', '面板与组件整体圆角', 0, 40, *tenth('shell.corner_radius_scale', 2.0), 20, fmt=lambda v: '×%.1f' % (v / 10)),
              Switch('界面动画', None, *c('shell.animation.enabled', True), True),
              Step('动画速度', '数值越大越快', 50, 300, *pct('shell.animation.speed', 1.0), 100, step=10, suffix='%')),
        Section('主题'),
        Group(Seg('明暗', None, [('dark', '深色'), ('light', '浅色')], *c('theme.shell_mode', 'dark'), 'dark'),
              Switch('深色时使用纯黑', None, *c('theme.pure_black_dark', True), True)),
        Section('位置与停靠'),
        Group(auto, city, Switch('底部程序坞', None, *c('dock.enabled', False), False)))


def page_media(app):
    get, set_ = P('pyrider3/media-capsule')
    return Page('媒体胶囊',
        Section('宽度', '栏上播放胶囊的最大宽度；标题短的时候胶囊会自己变窄，超过最大宽度的标题会滚动'),
        Group(Step('最大宽度', None, 96, 720, lambda: get('max_width', 360), lambda v: set_('max_width', v), 360, step=10, suffix=' px'),
              Seg('标题滚动', None, [('never', '不滚动'), ('hover', '悬停时'), ('always', '一直滚动')],
                  lambda: get('title_scroll', 'hover'), lambda v: set_('title_scroll', v), 'hover'),
              Step('滚动速度', '数值越大越快', 8, 60, lambda: get('scroll_speed', 22), lambda v: set_('scroll_speed', v), 22, step=2)),
        Section('频谱'),
        Group(Switch('显示音频频谱', '胶囊底部随音乐跳动的频谱', lambda: get('audio_spectrum', True), lambda v: set_('audio_spectrum', v), True),
              Step('频谱条数', None, 8, 64, lambda: get('audio_spectrum_bands', 20), lambda v: set_('audio_spectrum_bands', v), 20, step=2)))


STYLE_FILE = Path.home() / '.local/state/desk-style/style.json'


def page_style(app):
    return Page('主题风格',
        Section('整体风格', '所有的岛和面板一起切换：下次打开时生效'),
        Group(Seg('风格', '黑色岛：纯黑底；液态玻璃：磨砂半透明，能隐约透出背后的内容，边缘有高光',
                  [('black', '黑色岛'), ('glass', '液态玻璃')],
                  lambda: B.json_get(STYLE_FILE, 'style', 'black'), lambda v: B.json_set(STYLE_FILE, 'style', v), 'black')),
        Group(Info('液态玻璃每次打开时会截取一次背景并模糊，所以背后的画面是打开那一刻的样子；颜色会随背景深浅自动调整，保证文字清楚。', 62), card=False))


CATEGORIES = [
    ('桌面', [('style', '主题风格', 'window', page_style), ('wallpaper', '壁纸', 'image', page_wallpaper), ('we', '动态壁纸', 'play', page_we),
            ('niri', '外观（niri）', 'window', page_niri)]),
    ('栏与岛', [('noctalia', '状态栏与 Noctalia', 'bar', page_noctalia), ('noti', '通知', 'bell', page_notifications),
              ('clock', '时钟', 'clock', page_clock), ('media', '媒体胶囊', 'play', page_media), ('notion', '日程', 'calendar', page_notion),
              ('hub', '中间刻度尺', 'grid', page_hub), ('osd', '提示弹窗', 'chat', page_osd)]),
]

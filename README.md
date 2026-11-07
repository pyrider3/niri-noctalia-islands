# niri-noctalia-islands

一套给 **niri + Noctalia**（Wayland）做的"黑色灵动岛"风格桌面组件：通知、时钟、日程、媒体、状态、设置，全部是 Cairo 手绘、弹簧动画、纯黑岛，能从栏上的胶囊里"长出来"。

A set of black "dynamic island" style components for **niri + Noctalia**: notifications, clock/calendar, schedule, media, status panels and a settings app. Everything is Cairo-drawn with spring animations and grows out of the bar capsules.

> 这是我自己的桌面配置整理出来的，不是通用发行版。能直接用的部分在下面，已知限制也写了。
> This is a personal setup cleaned up for sharing, not a polished distro. Known limits are listed below.

## 里面有什么 / What's inside

| 目录 | 内容 |
|---|---|
| `notifd/` | 自己的通知守护进程（D-Bus `org.freedesktop.Notifications`）：5 种样式（深色卡片、亮色磨砂、灵动岛、栏内胶囊、铃铛摇出）、提示音、历史、勿扰 |
| `noctalia/plugins/notifd-bell` | 栏上的通知铃铛，未读数、勿扰，通知从铃铛里摇出来 |
| `noctalia/plugins/clock-island` | 数字翻滚的时钟 + 天气图标，点开是日历岛，带计时器 / 番茄钟 / 秒表 |
| `noctalia/plugins/notion-now` | 当前日程：合并 Notion 数据库，时间轴里直接看到事件，开始前提醒横幅 |
| `noctalia/plugins/media-capsule` | 播放胶囊 + 播放器岛（封面、频谱、进度） |
| `noctalia/plugins/status-capsule` | 蓝牙 / Wi-Fi / 音量 / 亮度四页的状态岛，长列表可滚动 |
| `noctalia/plugins/cyber-ruler` | 赛博刻度尺（工作区与窗口），加了"黑色灵动岛模式"和事件提示：勿扰、麦克风、输入法、切歌等从胶囊里长出黑岛 |
| `noctalia/plugins/center-hub` | 早期的中间枢纽实验，已被 cyber-ruler 的事件提示取代，留作参考 |
| `noctalia/plugins/grok-bot` | Grok Bot 面板的改版（原作者见下） |
| `desk-settings/` | 同风格的设置应用：壁纸、Wallpaper Engine、niri 外观、栏与 Noctalia、各组件设置，改动可撤销 |
| `niri/` | 脱敏后的 `config.kdl` 示例、模糊 / 浮动模式的 include 和脚本 |
| `noctalia/settings.example.toml` | 精简的 Noctalia 设置示例（不含壁纸、位置、账号） |

## 依赖 / Requirements

- niri ≥ 26.04（用到 include 与 `niri msg --json`）、Noctalia v5.4.x（plugin_api 43）
- Python 3.12+，`pygobject`、`pycairo`、GTK 4、**gtk4-layer-shell**（岛都是 layer-shell 窗口，需要 `LD_PRELOAD` 它，代码里已处理）
- `grim`（岛靠截图里的颜色标记定位栏上图标）、`pipewire` / `wpctl` / `pactl`、`nmcli`、`bluetoothctl`、`playerctl`
- 可选：`fcitx5`（输入法切换提示）、`linux-wallpaperengine`（动态壁纸页）、`node`（grok-bot）、`kew`（切歌通知转岛）

## 安装 / Install

```bash
git clone https://github.com/pyrider3/niri-noctalia-islands.git
cd niri-noctalia-islands
./install.sh --dry-run     # 先看会复制什么
./install.sh               # 复制 notifd、desk-settings、Noctalia 插件到 ~/.config
./install.sh --niri        # 同时装 niri 的 include 与脚本（不会覆盖你的 config.kdl）
```

脚本只做复制，已有目录会先改名备份（`*.bak-时间戳`），并把占位符 `__HOME__` 换成你的家目录。**不会**改你的 Noctalia `settings.toml`：把 `noctalia/settings.example.toml` 里需要的部分自己合并进去，启用插件并摆好栏布局。

接管通知（可随时撤销）：

```bash
~/.config/notifd/notifd-ctl.sh on     # 开
~/.config/notifd/notifd-ctl.sh off    # 关，回到 Noctalia 自带
```

打开设置应用：`python3 ~/.config/desk-settings/ds_app.py`（安装后也有桌面入口"桌面设置"）。

## 已知限制 / Known limits

- 这是个人环境：缩放 1.75、165 Hz 屏幕、中文界面上调出来的。别的分辨率和缩放比例下，岛的位置靠"栏上图标颜色标记"实时测量，大体能跟上，但没有大范围测试。
- Noctalia 不会自动读取外部对 `settings.toml` 的改动，之后任何一次 `config-set` 会用它内存里的旧值覆盖。直接改文件后请执行 `noctalia msg config-reload`。
- 事件提示要把对应的 Noctalia OSD 关掉才不会重复（`osd.kinds`：`media`、`privacy`、`keyboard_layout` 等）。设置应用的"提示弹窗"页可以改。
- 刻度尺的"黑色灵动岛模式"和从胶囊里长出提示，目前只支持 `merged`（合并刻度）主题。
- Notion 日程需要你自己的 Notion 集成密钥，存放在你本机的状态目录，**不在本仓库里**。
- 没有放别人的东西：niri 动画预设（如 nirimation、iNiR）请自行取用，放进 `~/.config/niri/animation-presets/` 后设置应用的"动画预设"会自动列出。

## 致谢 / Credits

- `grok-bot` 改自 Hector Marquez 的 [omarchy-grok-bot](https://github.com/hmarquez-solutions/omarchy-grok-bot)（MIT，许可证保留在该目录）。
- `cyber-ruler` 是我自己的项目 [noctalia-cyber-ruler](https://github.com/pyrider3/noctalia-cyber-ruler) 的本地版本。
- 感谢 niri、Noctalia 项目本身。

## 许可 / License

MIT，见 [LICENSE](LICENSE)。

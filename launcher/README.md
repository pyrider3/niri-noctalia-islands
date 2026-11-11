# Launcher add-ons (iRiS / iNiR-based launcher)

Extra search modes for the [iRiS launcher](https://github.com/pyrider3/lilt-launcher)-style palette
(an iNiR derivative running under quickshell). These are **patches + helper scripts**, not a full launcher.

| Prefix | What it does |
|---|---|
| `.keyword` | File search: SQLite index of your home dir (pinyin + initials for Chinese names), `Ctrl+Enter` reveals the folder, `Ctrl+Shift+C` copies the path |
| `;keyword` | Clipboard history (text only, pinyin search). Fed by `wl-paste --watch`; entries from password managers (`x-kde-passwordManagerHint`) are skipped. Stored in `~/.local/state/launcher-files/clip.db` (mode 600) |
| `@keyword` | Window switcher over `niri msg --json windows`, with app icons |
| (plain) | Pinyin / initials for Chinese app names (`wx` → 微信); apps, files and windows you use often rank higher (`usage.json`) |

## Contents
- `files/launcher_files.py` – file index (`index`) and query; `files/launcher_extra.py` – clipboard, windows, usage counts; `files/config.example.json` → `~/.config/launcher-files/config.json`
- `qml/` – new singletons: `FileSearch.qml`, `LauncherExtra.qml` (register both in `services/qmldir`), `Pinyin.qml` + `pinyin_table.js` (generated from the fcitx5/libime dictionary)
- `patches/` – diffs against the launcher source for `AppSearch.qml`, `LauncherSearch.qml`, `IrisPalette.qml` and the `iris-launcher` wrapper (adds a `prewarm` mode)
- `systemd/` – user units: periodic index rebuild, clipboard watcher, launcher pre-start (sets `LANG=zh_CN` — adjust for your locale)

## Install (rough)
1. Copy `files/*` to `~/.local/share/codex-iris-launcher/files/`; `qml/*` into the launcher `source/` tree (`services/` and `modules/common/functions/`); append the two `singleton` lines to `services/qmldir`.
2. Apply the patches with `patch -p0` from the launcher base dir (they are small; review them first).
3. Install the units into `~/.config/systemd/user/` (replace `__HOME__`), then `systemctl --user enable --now launcher-files-index.timer launcher-clip.service iris-launcher-warm.service`.

Privacy note: the clipboard watcher records what you copy. Disable with `systemctl --user disable --now launcher-clip` and delete `clip.db`.

The patched QML files derive from iNiR (GPL-3.0); the patches keep that licence.

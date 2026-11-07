#!/usr/bin/env bash
# Install niri-noctalia-islands into ~/.config.
#   ./install.sh            copy notifd, desk-settings and the Noctalia plugins
#   ./install.sh --niri     also install the niri include files and scripts (config.kdl is never overwritten)
#   ./install.sh --dry-run  show what would be copied
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DRY=0; NIRI=0
for a in "$@"; do case "$a" in --dry-run) DRY=1;; --niri) NIRI=1;; -h|--help) sed -n '2,6p' "$0"; exit 0;; *) echo "unknown option: $a" >&2; exit 2;; esac; done

say() { printf '  %s\n' "$*"; }
install_dir() {            # install_dir <src> <dst>
  local src="$1" dst="$2"
  if [ -e "$dst" ]; then say "backup  $dst -> $dst.bak-$STAMP"; [ $DRY = 1 ] || mv "$dst" "$dst.bak-$STAMP"; fi
  say "install $dst"
  [ $DRY = 1 ] && return 0
  mkdir -p "$dst"
  cp -a "$src/." "$dst/"
  # fill in the user's home directory wherever a file carries the placeholder
  { grep -rIl "__HOME__" "$dst" 2>/dev/null || true; } | while read -r f; do sed -i "s#__HOME__#$HOME#g" "$f"; done
}

echo "Installing into $CFG"
install_dir "$HERE/notifd"        "$CFG/notifd"
install_dir "$HERE/desk-settings" "$CFG/desk-settings"
for p in "$HERE"/noctalia/plugins/*/; do install_dir "$p" "$CFG/noctalia/plugins/$(basename "$p")"; done

if [ $NIRI = 1 ]; then
  mkdir -p "$CFG/niri"
  for f in "$HERE"/niri/*.kdl; do
    n="$(basename "$f")"
    if [ "$n" = config.kdl ]; then dst="$CFG/niri/config.islands-example.kdl"; else dst="$CFG/niri/$n"; fi
    [ -e "$dst" ] && { say "backup  $dst -> $dst.bak-$STAMP"; [ $DRY = 1 ] || mv "$dst" "$dst.bak-$STAMP"; }
    say "install $dst"; [ $DRY = 1 ] || { cp -a "$f" "$dst"; sed -i "s#__HOME__#$HOME#g" "$dst"; }
  done
  [ $DRY = 1 ] || { mkdir -p "$CFG/niri/animation-presets" "$CFG/niri/scripts"
    [ -e "$CFG/niri/animation-presets/active.kdl" ] || cp "$HERE/niri/animation-presets/active.kdl" "$CFG/niri/animation-presets/active.kdl"
    cp -a "$HERE"/niri/scripts/. "$CFG/niri/scripts/"; sed -i "s#__HOME__#$HOME#g" "$CFG"/niri/scripts/* 2>/dev/null || true; }
  say "niri: your config.kdl was NOT touched. Compare with config.islands-example.kdl and add the include lines you want."
fi

if [ $DRY = 0 ]; then
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/desk-settings.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=桌面设置
Name[en]=Desktop Settings
Comment=Noctalia, niri and the islands in one place
Exec=python3 $CFG/desk-settings/ds_app.py
Icon=preferences-system-symbolic
Terminal=false
Categories=Settings;
DESK
fi
cat <<'NEXT'

Next steps
  1. Merge noctalia/settings.example.toml into ~/.local/state/noctalia/settings.toml (enable the plugins, set bar layout).
  2. Take over notifications:   ~/.config/notifd/notifd-ctl.sh on     (undo: notifd-ctl.sh off)
  3. Open the settings app:     python3 ~/.config/desk-settings/ds_app.py
See README.md for dependencies.
NEXT

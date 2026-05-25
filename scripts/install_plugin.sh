#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${KRITA_PYKRITA_DIR:-}" ]]; then
  TARGET_DIR="$KRITA_PYKRITA_DIR"
elif flatpak info org.kde.krita >/dev/null 2>&1; then
  TARGET_DIR="$HOME/.var/app/org.kde.krita/data/krita/pykrita"
else
  TARGET_DIR="$HOME/.local/share/krita/pykrita"
fi

mkdir -p "$TARGET_DIR"
ln -sfn "$ROOT_DIR/pykrita/codex_krita" "$TARGET_DIR/codex_krita"
ln -sfn "$ROOT_DIR/pykrita/codex_krita.desktop" "$TARGET_DIR/codex_krita.desktop"

echo "Installed Codex for Krita into $TARGET_DIR"
echo "Restart Krita and enable the plugin in Settings > Configure Krita > Python Plugin Manager."

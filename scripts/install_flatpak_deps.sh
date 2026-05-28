#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${CODEX_REPO_DIR:-$ROOT_DIR/.vendor/codex}"

if [[ -z "${CODEX_SDK_PYTHON:-}" ]]; then
  if [[ ! -d "$VENDOR_DIR/.git" ]]; then
    mkdir -p "$(dirname "$VENDOR_DIR")"
    git clone https://github.com/openai/codex.git "$VENDOR_DIR"
  else
    git -C "$VENDOR_DIR" pull --ff-only
  fi
  CODEX_SDK_PYTHON="$VENDOR_DIR/sdk/python"
fi

if [[ -d "$CODEX_SDK_PYTHON" ]]; then
  flatpak run --filesystem="$ROOT_DIR" --command=python3 org.kde.krita \
    -m pip install --user pydantic
  flatpak run --filesystem="$ROOT_DIR" --command=python3 org.kde.krita \
    -c "import sys; sys.path[:0]=['$CODEX_SDK_PYTHON/src']; import openai_codex; print('Codex SDK import ready')"
else
  echo "Codex SDK Python directory not found: $CODEX_SDK_PYTHON" >&2
  exit 1
fi

NATIVE_CODEX_BIN="/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex"
if [[ -x "$NATIVE_CODEX_BIN" ]]; then
  FLATPAK_CODEX_BIN="/var/run/host$NATIVE_CODEX_BIN"
elif command -v codex >/dev/null 2>&1; then
  HOST_CODEX_BIN="$(command -v codex)"
  FLATPAK_CODEX_BIN="/var/run/host$HOST_CODEX_BIN"
else
  FLATPAK_CODEX_BIN=""
fi

CONFIG_DIR="$HOME/.var/app/org.kde.krita/data/krita/krita-codex"
CONFIG_PATH="$CONFIG_DIR/config.json"
mkdir -p "$CONFIG_DIR"
python3 - "$CONFIG_PATH" "$CODEX_SDK_PYTHON" "$FLATPAK_CODEX_BIN" <<'PY'
import json
import sys

path, sdk, codex_bin = sys.argv[1:4]
config = {"sdk_python_dir": sdk}
if codex_bin:
    config["codex_bin"] = codex_bin
with open(path, "w", encoding="utf-8") as config_file:
    json.dump(config, config_file, indent=2, sort_keys=True)
PY

echo "Prepared bundled Codex SDK/runtime for Krita Flatpak."
echo "Restart Krita, open the Codex docker, and run Check Setup."

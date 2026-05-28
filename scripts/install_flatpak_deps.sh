#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${CODEX_REPO_DIR:-$ROOT_DIR/.vendor/codex}"

if [[ -z "${CODEX_SDK_PYTHON:-}" ]]; then
  CODEX_SDK_PYTHON="$VENDOR_DIR/sdk/python"
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

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value"
}

{
  echo "{"
  if [[ -d "$CODEX_SDK_PYTHON" && -n "$FLATPAK_CODEX_BIN" ]]; then
    printf '  "sdk_python_dir": "%s",\n' "$(json_escape "$CODEX_SDK_PYTHON")"
    printf '  "codex_bin": "%s"\n' "$(json_escape "$FLATPAK_CODEX_BIN")"
  elif [[ -d "$CODEX_SDK_PYTHON" ]]; then
    printf '  "sdk_python_dir": "%s"\n' "$(json_escape "$CODEX_SDK_PYTHON")"
  elif [[ -n "$FLATPAK_CODEX_BIN" ]]; then
    printf '  "codex_bin": "%s"\n' "$(json_escape "$FLATPAK_CODEX_BIN")"
  fi
  echo "}"
} > "$CONFIG_PATH"

echo "Prepared Codex binary config for Krita Flatpak."
echo "Restart Krita, open the Codex docker, and run Check Setup."

# Krita Codex

Experimental Krita extension that embeds Codex directly into the Krita UI for image-first creative workflows.

The plugin talks to the local Codex SDK/app-server from a Qt worker thread inside Krita's Python process. It does not use MCP, does not require a separate bridge service, and does not use `OPENAI_API_KEY` directly.

## Features

- Analyze the current document, active layer, or selection through Codex.
- Ask Codex to generate or edit image artifacts for Krita and attach returned PNG files to the active document.
- Plan and generate animation frames from a dedicated `Codex Animation` docker for storyboard, inbetween, loop, and cleanup workflows.
- Ask Codex to generate Krita Python scripts and execute them through the plugin.
- Keep agent actions non-destructive by default: generated images become new layers/documents and script runs are logged.

## Requirements

- Krita with Python plugin support enabled.
- Local Codex already authenticated/configured through the normal Codex flow.
- The bundled `openai_codex` SDK files from the Codex repo.

The official Codex SDK docs describe the Python SDK as experimental and say it controls the local Codex app-server over JSON-RPC. The plugin uses that SDK directly rather than calling the OpenAI API SDK.

## Install Codex

Install the local Codex CLI first. On macOS/Linux, the official standalone installer is:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex
```

The first `codex` run opens the authentication flow. The plugin expects that local Codex is already signed in and usable from a terminal.

After importing the plugin in Krita, open `Settings > Dockers > Codex` and click `Check Setup`. If the Python SDK is missing, the plugin downloads the Codex repo archive, installs `sdk/python` into Krita's Python environment, saves the SDK path in Krita's data directory, and then prints the final setup status.

## Package Plugin For Import

Build a ZIP that Krita can import from any installation with Python plugin support:

```bash
./scripts/package_plugin.py
```

This writes:

```text
dist/codex_krita.zip
```

In Krita, open `Tools > Scripts > Import Python Plugin from File`, select `dist/codex_krita.zip`, restart Krita, then enable `Codex for Krita` in the Python Plugin Manager.

The ZIP contains the Krita plugin only. The target Krita environment still needs access to the local Codex binary. Open `Settings > Dockers > Codex` and click `Check Setup` to prepare the SDK and verify the Codex binary path.

## Publish GitHub Release

The release workflow builds `dist/codex_krita.zip` and attaches it to a GitHub Release when a `v*` tag is pushed:

```bash
git tag v0.1.0
git push origin v0.1.0
```

It can also be run manually from GitHub Actions with a release tag name.

## Install Plugin For Development

Install the Krita plugin by symlinking it into Krita's `pykrita` resource directory:

```bash
./scripts/install_plugin.sh
```

For Flatpak Krita (`org.kde.krita`), the installer targets:

```text
~/.var/app/org.kde.krita/data/krita/pykrita
```

Restart Krita, enable `Codex for Krita` in the Python Plugin Manager, then open `Settings > Dockers > Codex`.
Animation tools are available as a separate docker at `Settings > Dockers > Codex Animation` and from `Tools > Scripts > Codex Animation`.

In the docker, use `Check Setup` first. It prepares the SDK if needed and reports any missing Codex binary configuration.

## Optional Flatpak Helper

`Check Setup` can prepare the SDK from inside the plugin. For development installs of Flatpak Krita, this helper does the same preparation from a terminal:

```bash
./scripts/install_flatpak_deps.sh
```

The script clones the Codex repo into `.vendor/codex` if needed, prepares the SDK runtime, and writes a plugin-local config file at `~/.var/app/org.kde.krita/data/krita/krita-codex/config.json`.

Verify from the Flatpak Python if needed:

```bash
flatpak run --filesystem="$PWD" --command=python3 org.kde.krita -c 'import os, sys; sys.path.insert(0, os.path.join(os.getcwd(), ".vendor/codex/sdk/python/src")); import openai_codex; print("ok")'
```

Do not use `flatpak override` for this plugin. Use `Check Setup` and `Save Config` in the docker instead.

Image generation and editing requests include the bundled Codex `imagegen` skill when it is available at `~/.codex/skills/.system/imagegen`.

## Native Krita Option

If Flatpak dependency management becomes painful, install Krita outside Flatpak and install the Codex SDK into the Python interpreter that Krita uses:

```bash
cd /path/to/codex/sdk/python
python3 -m pip install -e .
```

For native Krita, `Check Setup` stores its managed SDK and config under `~/.local/share/krita/krita-codex` unless `XDG_DATA_HOME` points Krita somewhere else.

Then set `KRITA_PYKRITA_DIR` before running `install_plugin.sh` if the native Krita resource path differs:

```bash
KRITA_PYKRITA_DIR=/path/to/krita/pykrita ./scripts/install_plugin.sh
```

## Development

Run tests that do not require Krita:

```bash
PYTHONPATH=service python3 -m unittest discover -s tests
```

`service/` remains only as an optional reference experiment. The Krita docker uses direct Codex SDK calls by default.

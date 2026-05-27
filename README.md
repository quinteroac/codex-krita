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

## Install Plugin

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

In the docker, use `Check Setup` first. If Krita Flatpak can see the host Codex binary, `Configure Codex` writes the needed Flatpak environment override automatically.

## Install Codex SDK For Flatpak Krita

Prepare the bundled SDK/runtime for Krita Flatpak:

```bash
./scripts/install_flatpak_deps.sh
```

The script clones the Codex repo into `.vendor/codex` if needed, prepares the SDK runtime, and writes a plugin-local config file at `~/.var/app/org.kde.krita/data/krita-codex/config.json`.

Verify from the Flatpak Python if needed:

```bash
flatpak run --filesystem=/home/victor/dev/krita-codex --command=python3 org.kde.krita -c 'import sys; sys.path.insert(0, "/home/victor/dev/krita-codex/.vendor/codex/sdk/python/src"); import openai_codex; print("ok")'
```

Do not use `flatpak override` for this plugin. Use `Check Setup` and `Save Config` in the docker instead.

Image generation and editing requests include the bundled Codex `imagegen` skill when it is available at `~/.codex/skills/.system/imagegen`.

## Native Krita Option

If Flatpak dependency management becomes painful, install Krita outside Flatpak and install the Codex SDK into the Python interpreter that Krita uses:

```bash
cd /path/to/codex/sdk/python
python3 -m pip install -e .
```

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

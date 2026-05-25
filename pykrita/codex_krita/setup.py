import importlib.util
import json
import os
import sys
import shutil
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = PLUGIN_DIR.parents[1]
VENDOR_SDK_DIR = REPO_ROOT / ".vendor" / "codex" / "sdk" / "python"
VENDOR_SDK_SRC_DIR = VENDOR_SDK_DIR / "src"
CONFIG_DIR = Path.home() / ".var" / "app" / "org.kde.krita" / "data" / "krita-codex"
CONFIG_PATH = CONFIG_DIR / "config.json"
IMAGEGEN_SKILL_PATH = Path(
    os.path.expanduser(os.environ.get("KRITA_CODEX_IMAGEGEN_SKILL", "~/.codex/skills/.system/imagegen"))
)


def codex_sdk_available():
    ensure_vendor_sdk_on_path()
    return importlib.util.find_spec("openai_codex") is not None


def ensure_vendor_sdk_on_path():
    sdk_dir = configured_sdk_dir()
    sdk_src_dir = sdk_dir / "src"
    if sdk_src_dir.exists():
        src = str(sdk_src_dir)
        sdk = str(sdk_dir)
        if sdk not in sys.path:
            sys.path.insert(0, sdk)
        if src not in sys.path:
            sys.path.insert(0, src)


def ensure_codex_runtime():
    ensure_vendor_sdk_on_path()
    return None


def read_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(str(CONFIG_PATH), "r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except Exception:
        return {}


def write_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(str(CONFIG_PATH), "w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2, sort_keys=True)


def configured_sdk_dir():
    value = read_config().get("sdk_python_dir")
    if value:
        return Path(value)
    return VENDOR_SDK_DIR


def find_codex_binary():
    config = read_config()
    configured = os.environ.get("KRITA_CODEX_BIN")
    candidates = [
        config.get("codex_bin"),
        configured,
        "/var/run/host/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex",
        "/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex",
        shutil.which("codex"),
        "/var/run/host/usr/bin/codex",
        "/var/run/host/usr/local/bin/codex",
        "/var/run/host/home/%s/.local/bin/codex" % os.environ.get("USER", ""),
        "/usr/bin/codex",
        "/usr/local/bin/codex",
        os.path.expanduser("~/.local/bin/codex"),
        os.path.expanduser("~/.npm-global/bin/codex"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def find_node_binary():
    candidates = [
        shutil.which("node"),
        "/var/run/host/usr/bin/node",
        "/var/run/host/usr/local/bin/node",
        "/usr/bin/node",
        "/usr/local/bin/node",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def diagnostics():
    codex_bin = find_codex_binary()
    node_bin = find_node_binary()
    sdk_dir = configured_sdk_dir()
    return {
        "sdk_available": codex_sdk_available(),
        "vendor_sdk": str(sdk_dir) if sdk_dir.exists() else None,
        "codex_bin": codex_bin,
        "imagegen_skill": str(IMAGEGEN_SKILL_PATH) if IMAGEGEN_SKILL_PATH.exists() else None,
        "node_bin": node_bin,
        "path": os.environ.get("PATH", ""),
        "env_codex_bin": os.environ.get("KRITA_CODEX_BIN"),
        "config_path": str(CONFIG_PATH),
        "is_flatpak": os.environ.get("FLATPAK") == "1",
    }


def save_detected_config(codex_bin=None):
    selected_codex_bin = codex_bin or find_codex_binary()
    if not selected_codex_bin:
        raise RuntimeError("Codex binary was not found.")

    config = read_config()
    config["sdk_python_dir"] = str(configured_sdk_dir())
    config["codex_bin"] = selected_codex_bin
    write_config(config)
    return "Saved Codex config to %s" % CONFIG_PATH


def apply_flatpak_codex_bin_override(codex_bin):
    return save_detected_config(codex_bin)


def setup_status_text():
    info = diagnostics()
    lines = []
    lines.append("Codex SDK: %s" % ("installed" if info["sdk_available"] else "missing"))
    lines.append("Bundled SDK path: %s" % (info["vendor_sdk"] or "not found"))
    lines.append("Codex binary: %s" % (info["codex_bin"] or "not found"))
    lines.append("Imagegen skill: %s" % (info["imagegen_skill"] or "not found"))
    lines.append("Node binary: %s" % (info["node_bin"] or "not found"))
    if info["is_flatpak"]:
        lines.append("Krita Flatpak: yes")
        lines.append("Config file: %s" % info["config_path"])
    if not info["sdk_available"]:
        lines.append("")
        lines.append("Run the plugin installer again so it can clone the Codex SDK into .vendor/codex.")
    if info["sdk_available"] and not info["codex_bin"]:
        lines.append("")
        lines.append("Install Codex or configure KRITA_CODEX_BIN.")
    if info["codex_bin"] and not info["node_bin"]:
        lines.append("")
        lines.append("Codex CLI needs node. Configure the Flatpak PATH so /var/run/host/usr/bin is visible.")
    return "\n".join(lines)

import importlib
import importlib.util
import json
import os
import sys
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = PLUGIN_DIR.parents[1]
VENDOR_SDK_DIR = REPO_ROOT / ".vendor" / "codex" / "sdk" / "python"
VENDOR_SDK_SRC_DIR = VENDOR_SDK_DIR / "src"
CONFIG_DIR = Path.home() / ".var" / "app" / "org.kde.krita" / "data" / "krita-codex"
CONFIG_PATH = CONFIG_DIR / "config.json"
MANAGED_CODEX_DIR = CONFIG_DIR / "vendor" / "codex"
CODEX_ARCHIVE_URL = "https://github.com/openai/codex/archive/refs/heads/main.zip"
IMAGEGEN_SKILL_PATH = Path(
    os.path.expanduser(os.environ.get("KRITA_CODEX_IMAGEGEN_SKILL", "~/.codex/skills/.system/imagegen"))
)


def codex_sdk_available():
    ensure_vendor_sdk_on_path()
    try:
        importlib.import_module("openai_codex")
        return True
    except Exception:
        return False


def _path_from_env(name):
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def _sdk_dir_valid(path):
    if not path:
        return False
    path = Path(path).expanduser()
    return (path / "src" / "openai_codex").is_dir() or (path / "openai_codex").is_dir()


def _sdk_dir_from_import():
    spec = importlib.util.find_spec("openai_codex")
    if not spec or not spec.origin:
        return None
    package_dir = Path(spec.origin).resolve().parent
    if package_dir.parent.name == "src":
        return package_dir.parent.parent
    return package_dir.parent


def _sdk_candidates(include_config=True):
    candidates = []
    if include_config:
        configured = read_config().get("sdk_python_dir")
        if configured:
            candidates.append(Path(configured).expanduser())

    codex_repo_dir = _path_from_env("CODEX_REPO_DIR")
    if codex_repo_dir:
        candidates.append(codex_repo_dir / "sdk" / "python")

    candidates.extend(
        candidate
        for candidate in (
            _path_from_env("KRITA_CODEX_SDK_PYTHON"),
            _path_from_env("CODEX_SDK_PYTHON"),
            VENDOR_SDK_DIR,
            MANAGED_CODEX_DIR / "sdk" / "python",
            PLUGIN_DIR.parent / ".vendor" / "codex" / "sdk" / "python",
            Path.home() / "dev" / "codex" / "sdk" / "python",
            Path.home() / "src" / "codex" / "sdk" / "python",
            _sdk_dir_from_import(),
        )
        if candidate
    )
    return candidates


def find_codex_sdk_dir():
    seen = set()
    for candidate in _sdk_candidates():
        candidate = Path(candidate).expanduser()
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if _sdk_dir_valid(candidate):
            return candidate
    return None


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


def install_sdk_package(sdk_dir):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "-e", str(sdk_dir)])


def ensure_managed_sdk_installed():
    detected = find_codex_sdk_dir()
    if detected:
        if not codex_sdk_available():
            install_sdk_package(detected)
        config = read_config()
        config["sdk_python_dir"] = str(detected)
        codex_bin = find_codex_binary()
        if codex_bin:
            config["codex_bin"] = codex_bin
        write_config(config)
        ensure_vendor_sdk_on_path()
        return "Codex SDK already available at %s" % detected

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="krita-codex-sdk-") as temp_dir:
        archive_path = Path(temp_dir) / "codex.zip"
        urllib.request.urlretrieve(CODEX_ARCHIVE_URL, str(archive_path))

        extract_dir = Path(temp_dir) / "extract"
        with zipfile.ZipFile(str(archive_path), "r") as archive:
            archive.extractall(str(extract_dir))

        roots = [path for path in extract_dir.iterdir() if path.is_dir()]
        if not roots:
            raise RuntimeError("Downloaded Codex archive did not contain a repository directory.")

        source_dir = roots[0]
        sdk_dir = source_dir / "sdk" / "python"
        if not _sdk_dir_valid(sdk_dir):
            raise RuntimeError("Downloaded Codex archive did not contain sdk/python.")

        if MANAGED_CODEX_DIR.exists():
            shutil.rmtree(str(MANAGED_CODEX_DIR))
        MANAGED_CODEX_DIR.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(source_dir), str(MANAGED_CODEX_DIR))

    managed_sdk_dir = MANAGED_CODEX_DIR / "sdk" / "python"
    install_sdk_package(managed_sdk_dir)

    config = read_config()
    config["sdk_python_dir"] = str(managed_sdk_dir)
    codex_bin = find_codex_binary()
    if codex_bin:
        config["codex_bin"] = codex_bin
    write_config(config)
    ensure_vendor_sdk_on_path()
    return "Installed Codex SDK at %s" % managed_sdk_dir


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
    detected = find_codex_sdk_dir()
    if detected:
        return detected
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
        "detected_sdk": str(find_codex_sdk_dir() or ""),
        "codex_bin": codex_bin,
        "imagegen_skill": str(IMAGEGEN_SKILL_PATH) if IMAGEGEN_SKILL_PATH.exists() else None,
        "node_bin": node_bin,
        "path": os.environ.get("PATH", ""),
        "env_codex_bin": os.environ.get("KRITA_CODEX_BIN"),
        "config_path": str(CONFIG_PATH),
        "is_flatpak": os.environ.get("FLATPAK") == "1",
    }


def save_config(sdk_dir=None, codex_bin=None):
    selected_sdk_dir = Path(sdk_dir).expanduser() if sdk_dir else find_codex_sdk_dir()
    selected_codex_bin = codex_bin or find_codex_binary()

    if not selected_sdk_dir or not _sdk_dir_valid(selected_sdk_dir):
        raise RuntimeError("Codex SDK Python directory was not found.")
    if not selected_codex_bin:
        raise RuntimeError("Codex binary was not found.")
    if not os.path.exists(selected_codex_bin) or not os.access(selected_codex_bin, os.X_OK):
        raise RuntimeError("Codex binary is not executable: %s" % selected_codex_bin)

    config = read_config()
    config["sdk_python_dir"] = str(selected_sdk_dir)
    config["codex_bin"] = selected_codex_bin
    write_config(config)
    return "Saved Codex config to %s" % CONFIG_PATH


def save_detected_config(codex_bin=None):
    return save_config(codex_bin=codex_bin)


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
        lines.append("Click Check Setup to download and install the Codex SDK into the plugin data directory.")
    if info["sdk_available"] and not info["codex_bin"]:
        lines.append("")
        lines.append("Install Codex or configure KRITA_CODEX_BIN.")
    if info["codex_bin"] and not info["node_bin"]:
        lines.append("")
        lines.append("Codex CLI needs node. Configure the Flatpak PATH so /var/run/host/usr/bin is visible.")
    return "\n".join(lines)

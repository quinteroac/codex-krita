import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
SETUP_MODULE = ROOT_DIR / "pykrita" / "codex_krita" / "setup.py"


def load_setup_module():
    spec = importlib.util.spec_from_file_location("codex_krita_setup_test", SETUP_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SetupConfigTests(unittest.TestCase):
    def test_native_config_uses_krita_data_dir(self):
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home}, clear=True):
                setup = load_setup_module()

        expected = Path(home) / ".local" / "share" / "krita" / "krita-codex" / "config.json"
        self.assertEqual(setup.CONFIG_PATH, expected)

    def test_xdg_data_home_is_respected(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as xdg_data:
            env = {"HOME": home, "XDG_DATA_HOME": xdg_data}
            with mock.patch.dict(os.environ, env, clear=True):
                setup = load_setup_module()

        expected = Path(xdg_data) / "krita" / "krita-codex" / "config.json"
        self.assertEqual(setup.CONFIG_PATH, expected)

    def test_native_config_does_not_read_flatpak_legacy_path(self):
        with tempfile.TemporaryDirectory() as home:
            legacy_path = (
                Path(home)
                / ".var"
                / "app"
                / "org.kde.krita"
                / "data"
                / "krita-codex"
                / "config.json"
            )
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(json.dumps({"sdk_python_dir": "/legacy"}), encoding="utf-8")

            with mock.patch.dict(os.environ, {"HOME": home}, clear=True):
                setup = load_setup_module()
                config = setup.read_config()

        self.assertEqual(config, {})

    def test_flatpak_can_read_legacy_config_path(self):
        with tempfile.TemporaryDirectory() as home:
            legacy_path = (
                Path(home)
                / ".var"
                / "app"
                / "org.kde.krita"
                / "data"
                / "krita-codex"
                / "config.json"
            )
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(json.dumps({"sdk_python_dir": "/legacy"}), encoding="utf-8")

            with mock.patch.dict(os.environ, {"HOME": home, "FLATPAK": "1"}, clear=True):
                setup = load_setup_module()
                config = setup.read_config()

        self.assertEqual(config, {"sdk_python_dir": "/legacy"})


if __name__ == "__main__":
    unittest.main()

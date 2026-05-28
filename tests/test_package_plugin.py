import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PACKAGE_SCRIPT = ROOT_DIR / "scripts" / "package_plugin.py"


def load_package_plugin_module():
    spec = importlib.util.spec_from_file_location("package_plugin", PACKAGE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackagePluginTests(unittest.TestCase):
    def test_archive_contains_krita_importer_directory_entry(self):
        package_plugin = load_package_plugin_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "codex_krita.zip"
            package_plugin.build_archive(output_path)

            with zipfile.ZipFile(output_path) as archive:
                names = archive.namelist()

        self.assertIn("codex_krita.desktop", names)
        self.assertIn("codex_krita/", names)
        self.assertIn("codex_krita/__init__.py", names)


if __name__ == "__main__":
    unittest.main()

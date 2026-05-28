import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
IMAGE_BRIDGE_MODULE = ROOT_DIR / "pykrita" / "codex_krita" / "image_bridge.py"


class FakeDocument:
    def __init__(self, width, height):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


def install_fake_modules():
    qtcore = types.ModuleType("PyQt5.QtCore")
    qtcore.QByteArray = bytes
    qtcore.QBuffer = object
    qtcore.QIODevice = types.SimpleNamespace(WriteOnly=1)
    qtgui = types.ModuleType("PyQt5.QtGui")
    qtgui.QColor = object
    qtgui.QImage = object
    krita = types.ModuleType("krita")
    krita.InfoObject = object
    krita.Krita = object
    sys.modules.setdefault("PyQt5", types.ModuleType("PyQt5"))
    sys.modules["PyQt5.QtCore"] = qtcore
    sys.modules["PyQt5.QtGui"] = qtgui
    sys.modules["krita"] = krita


def load_image_bridge_module():
    install_fake_modules()
    spec = importlib.util.spec_from_file_location("codex_krita_image_bridge_test", IMAGE_BRIDGE_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImageBridgeTests(unittest.TestCase):
    def test_blend_alpha_feathers_inside_selection_edge(self):
        image_bridge = load_image_bridge_module()

        self.assertEqual(image_bridge.blend_alpha(255, 0, 0, 64, 24), 0)
        self.assertEqual(image_bridge.blend_alpha(255, 0, 12, 64, 24), 127)
        self.assertEqual(image_bridge.blend_alpha(255, 0, 24, 64, 24), 255)

    def test_blend_alpha_feathers_outside_padding_edge(self):
        image_bridge = load_image_bridge_module()

        self.assertEqual(image_bridge.blend_alpha(0, 40, 0, 64, 24), 255)
        self.assertEqual(image_bridge.blend_alpha(0, 52, 0, 64, 24), 127)
        self.assertEqual(image_bridge.blend_alpha(0, 64, 0, 64, 24), 0)

    def test_clip_packed_to_document_clips_negative_offsets(self):
        image_bridge = load_image_bridge_module()
        packed = {
            "pixels": bytearray(
                [
                    1,
                    1,
                    1,
                    0,
                    2,
                    2,
                    2,
                    128,
                    3,
                    3,
                    3,
                    255,
                    4,
                    4,
                    4,
                    255,
                ]
            ),
            "width": 2,
            "height": 2,
            "transparent": 1,
            "semi_transparent": 1,
        }

        clipped = image_bridge.clip_packed_to_document(packed, FakeDocument(10, 10), -1, -1)

        self.assertEqual(clipped["x"], 0)
        self.assertEqual(clipped["y"], 0)
        self.assertEqual(clipped["width"], 1)
        self.assertEqual(clipped["height"], 1)
        self.assertEqual(bytes(clipped["pixels"]), bytes([4, 4, 4, 255]))

    def test_clip_packed_to_document_rejects_outside_image(self):
        image_bridge = load_image_bridge_module()
        packed = {
            "pixels": bytearray([1, 1, 1, 255]),
            "width": 1,
            "height": 1,
            "transparent": 0,
            "semi_transparent": 0,
        }

        self.assertIsNone(image_bridge.clip_packed_to_document(packed, FakeDocument(10, 10), 12, 12))


if __name__ == "__main__":
    unittest.main()

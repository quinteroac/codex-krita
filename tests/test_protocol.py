import unittest

from krita_codex_service.protocol import (
    ProtocolError,
    image_data_url,
    parse_rpc_request,
    validate_script,
)


class ProtocolTests(unittest.TestCase):
    def test_parse_rpc_request_defaults_params(self):
        request = parse_rpc_request({"id": 1, "method": "generate_image"})

        self.assertEqual(request.id, 1)
        self.assertEqual(request.method, "generate_image")
        self.assertEqual(request.params, {})

    def test_parse_rpc_request_rejects_bad_params(self):
        with self.assertRaises(ProtocolError):
            parse_rpc_request({"method": "generate_image", "params": []})

    def test_validate_script_rejects_denied_tokens(self):
        with self.assertRaises(ProtocolError):
            validate_script("import subprocess\nsubprocess.run(['rm', '-rf', '/tmp/x'])")

    def test_validate_script_accepts_basic_krita_code(self):
        validate_script("doc = Krita.instance().activeDocument()\nprint(doc.name() if doc else 'none')")

    def test_image_data_url_wraps_base64(self):
        self.assertEqual(image_data_url("abc"), "data:image/png;base64,abc")

    def test_image_data_url_preserves_existing_data_url(self):
        value = "data:image/jpeg;base64,abc"
        self.assertEqual(image_data_url(value), value)


if __name__ == "__main__":
    unittest.main()

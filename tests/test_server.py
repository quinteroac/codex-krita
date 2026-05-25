import unittest

from krita_codex_service.server import ServiceState


class ServiceStateTests(unittest.TestCase):
    def test_service_state_is_lazy(self):
        state = ServiceState(vision_model="vision", codex_model="codex")

        self.assertEqual(state.vision_model, "vision")
        self.assertEqual(state.codex_model, "codex")
        self.assertIsNone(state._openai_ops)
        self.assertIsNone(state._codex_bridge)


if __name__ == "__main__":
    unittest.main()

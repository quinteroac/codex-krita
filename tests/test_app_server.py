import importlib.util
import queue
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_SERVER_MODULE = ROOT_DIR / "pykrita" / "codex_krita" / "app_server.py"


def load_app_server_module():
    spec = importlib.util.spec_from_file_location("codex_krita_app_server_test", APP_SERVER_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AppServerTests(unittest.TestCase):
    def test_turn_stream_ignores_events_for_other_turns(self):
        app_server = load_app_server_module()
        client = app_server.AppServerClient.__new__(app_server.AppServerClient)
        client._notifications = queue.Queue()
        client._notifications.put(
            (
                "item/completed",
                {"turnId": "other-turn", "item": {"id": "other", "type": "agentMessage"}},
            )
        )
        client._notifications.put(
            (
                "turn/completed",
                {"turn": {"id": "target-turn", "status": "completed"}},
            )
        )

        events = list(client.turn_stream("target-turn"))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].method, "turn/completed")
        self.assertEqual(events[0].payload.turn.id, "target-turn")

    def test_notification_turn_id_reads_snake_case_and_camel_case(self):
        app_server = load_app_server_module()

        self.assertEqual(
            app_server._notification_turn_id("item/completed", {"turnId": "camel"}),
            "camel",
        )
        self.assertEqual(
            app_server._notification_turn_id("item/completed", {"turn_id": "snake"}),
            "snake",
        )
        self.assertEqual(
            app_server._notification_turn_id("turn/completed", {"turn": {"id": "nested"}}),
            "nested",
        )


if __name__ == "__main__":
    unittest.main()

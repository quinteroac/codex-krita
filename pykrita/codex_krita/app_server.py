import json
import os
import queue
import subprocess
import threading
import uuid
from types import SimpleNamespace


def _to_namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _to_namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_to_namespace(item) for item in value]
    return value


def _wire_input_item(item):
    if isinstance(item, str):
        return {"type": "text", "text": item}
    if isinstance(item, dict):
        return item
    raise TypeError("Unsupported Codex input item: %r" % (item,))


def text_input(text):
    return {"type": "text", "text": text}


def local_image_input(path):
    return {"type": "localImage", "path": path}


def skill_input(name, path):
    return {"type": "skill", "name": name, "path": path}


class AppServerClient:
    def __init__(self, codex_bin, model=None):
        if not codex_bin:
            raise RuntimeError("Codex binary was not found. Open the Codex docker and save its path.")
        self.codex_bin = codex_bin
        self.model = model
        self._proc = None
        self._lock = threading.Lock()
        self._responses = {}
        self._notifications = queue.Queue()
        self._stderr_lines = []
        self._reader_thread = None
        self._stderr_thread = None

    def __enter__(self):
        self.start()
        self.initialize()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()

    def start(self):
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(
            [self.codex_bin, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=os.path.expanduser("~"),
            bufsize=1,
        )
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_thread.start()

    def close(self):
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

    def initialize(self):
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "krita_codex",
                    "title": "Krita Codex",
                    "version": "0.1",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        self.notify("initialized")

    def thread_start(self):
        params = {
            "approvalPolicy": "on-request",
            "approvalsReviewer": "auto_review",
        }
        if self.model:
            params["model"] = self.model
        result = self.request("thread/start", params)
        return result["thread"]["id"]

    def turn_start(self, thread_id, input_items):
        if isinstance(input_items, str):
            wire_input = [text_input(input_items)]
        else:
            wire_input = [_wire_input_item(item) for item in input_items]
        result = self.request("turn/start", {"threadId": thread_id, "input": wire_input})
        return result["turn"]["id"]

    def turn_stream(self, turn_id):
        while True:
            method, payload = self._notifications.get()
            event = SimpleNamespace(method=method, payload=_to_namespace(payload))
            yield event
            turn = payload.get("turn") if isinstance(payload, dict) else None
            if method == "turn/completed" and isinstance(turn, dict) and turn.get("id") == turn_id:
                break

    def request(self, method, params=None):
        request_id = str(uuid.uuid4())
        waiter = queue.Queue(maxsize=1)
        self._responses[request_id] = waiter
        self._write({"id": request_id, "method": method, "params": params or {}})
        response = waiter.get()
        if isinstance(response, BaseException):
            raise response
        if "error" in response:
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(message or "Codex app-server request failed.")
        return response.get("result")

    def notify(self, method, params=None):
        message = {"method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

    def _write(self, payload):
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Codex app-server is not running.")
        with self._lock:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()

    def _read_loop(self):
        try:
            while self._proc is not None and self._proc.stdout is not None:
                line = self._proc.stdout.readline()
                if not line:
                    raise RuntimeError("Codex app-server closed stdout. %s" % self._stderr_tail())
                message = json.loads(line)
                if "method" in message and "id" in message:
                    self._write({"id": message["id"], "result": self._handle_server_request(message)})
                    continue
                if "method" in message:
                    self._notifications.put((message["method"], message.get("params") or {}))
                    continue
                response_id = message.get("id")
                waiter = self._responses.pop(response_id, None)
                if waiter is not None:
                    waiter.put(message)
        except BaseException as exc:
            for waiter in list(self._responses.values()):
                waiter.put(exc)
            self._responses.clear()

    def _stderr_loop(self):
        try:
            while self._proc is not None and self._proc.stderr is not None:
                line = self._proc.stderr.readline()
                if not line:
                    break
                self._stderr_lines.append(line.rstrip("\n"))
                self._stderr_lines = self._stderr_lines[-80:]
        except Exception:
            pass

    def _handle_server_request(self, message):
        method = message.get("method")
        if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            return {"decision": "accept"}
        return {}

    def _stderr_tail(self):
        return "\n".join(self._stderr_lines[-20:])

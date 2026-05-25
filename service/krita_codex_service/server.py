from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .codex_bridge import CodexBridge
from .openai_ops import OpenAIOps
from .protocol import ProtocolError, error_response, ok_response, parse_rpc_request, validate_script


class ServiceState:
    def __init__(self, vision_model: str, codex_model: str) -> None:
        self.vision_model = vision_model
        self.codex_model = codex_model
        self._openai_ops: OpenAIOps | None = None
        self._codex_bridge: CodexBridge | None = None

    @property
    def openai_ops(self) -> OpenAIOps:
        if self._openai_ops is None:
            self._openai_ops = OpenAIOps(model=self.vision_model)
        return self._openai_ops

    @property
    def codex_bridge(self) -> CodexBridge:
        if self._codex_bridge is None:
            self._codex_bridge = CodexBridge(model=self.codex_model)
        return self._codex_bridge


class RpcHandler(BaseHTTPRequestHandler):
    state: ServiceState

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._send_json({"ok": True, "service": "krita-codex"})

    def do_POST(self) -> None:
        if self.path != "/rpc":
            self.send_error(404)
            return

        request_id: str | int | None = None
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            request = parse_rpc_request(payload)
            request_id = request.id
            result = self.dispatch(request.method, request.params)
            self._send_json(ok_response(request_id, result))
        except Exception as exc:
            self._send_json(error_response(request_id, str(exc)), status=400)

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "analyze_image":
            return self.state.openai_ops.analyze_image(
                image_b64=params["image_b64"],
                question=params.get("question", ""),
                mime_type=params.get("mime_type", "image/png"),
            )
        if method == "generate_image":
            return self.state.openai_ops.generate_image(
                prompt=params["prompt"],
                size=params.get("size", "1024x1024"),
                quality=params.get("quality", "medium"),
            )
        if method == "edit_image":
            return self.state.openai_ops.edit_image(
                prompt=params["prompt"],
                image_b64=params["image_b64"],
                mask_b64=params.get("mask_b64"),
                size=params.get("size", "1024x1024"),
                quality=params.get("quality", "medium"),
            )
        if method == "propose_script":
            return self.state.codex_bridge.propose_script(
                task=params["task"],
                document_context=params.get("document_context"),
            )
        if method == "validate_script":
            validate_script(params["code"])
            return {"valid": True}

        raise ProtocolError(f"Unknown method: {method}")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host: str, port: int, vision_model: str, codex_model: str) -> ThreadingHTTPServer:
    handler = type("ConfiguredRpcHandler", (RpcHandler,), {})
    handler.state = ServiceState(vision_model=vision_model, codex_model=codex_model)
    return ThreadingHTTPServer((host, port), handler)

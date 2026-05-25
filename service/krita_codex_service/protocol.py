from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ProtocolError(ValueError):
    pass


DENIED_SCRIPT_TOKENS = (
    "subprocess",
    "os.system",
    "shutil.rmtree",
    "Path.home",
    "socket.",
    "requests.",
    "urllib.request",
    "open(",
    "__import__",
    "eval(",
    "exec(",
)


@dataclass(frozen=True)
class RpcRequest:
    id: str | int | None
    method: str
    params: dict[str, Any]


def parse_rpc_request(payload: dict[str, Any]) -> RpcRequest:
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError("RPC request must include a non-empty string method.")

    params = payload.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ProtocolError("RPC params must be an object.")

    return RpcRequest(id=payload.get("id"), method=method, params=params)


def ok_response(request_id: str | int | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: str | int | None, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"message": message}}


def validate_script(code: str) -> None:
    if not isinstance(code, str) or not code.strip():
        raise ProtocolError("Script code is empty.")

    lowered = code.lower()
    for token in DENIED_SCRIPT_TOKENS:
        if token.lower() in lowered:
            raise ProtocolError(f"Script contains denied token: {token}")


def image_data_url(image_b64: str, mime_type: str = "image/png") -> str:
    if image_b64.startswith("data:"):
        return image_b64
    return f"data:{mime_type};base64,{image_b64}"

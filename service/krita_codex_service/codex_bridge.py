from __future__ import annotations

import json
from typing import Any

from .protocol import validate_script


SCRIPT_SYSTEM_PROMPT = """You generate Python scripts for Krita.
Return only JSON with keys: code, reason, expected_effect.
The code runs inside Krita's Python environment with `from krita import *` available.
Avoid destructive file operations. Prefer creating new layers or reversible document changes.
"""


class CodexBridge:
    def __init__(self, model: str = "gpt-5.4") -> None:
        try:
            from codex_app_server import Codex
        except Exception as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "The experimental Codex Python SDK is not installed. "
                "Install it from the Codex repo's sdk/python directory."
            ) from exc

        self._codex_cls = Codex
        self._model = model

    def propose_script(self, task: str, document_context: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt = {
            "system": SCRIPT_SYSTEM_PROMPT,
            "task": task,
            "document_context": document_context or {},
        }
        with self._codex_cls() as codex:
            thread = codex.thread_start(model=self._model)
            result = thread.run(json.dumps(prompt))

        raw = result.final_response.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.removeprefix("json").strip()

        payload = json.loads(raw)
        code = payload.get("code", "")
        validate_script(code)
        return {
            "code": code,
            "reason": payload.get("reason", ""),
            "expected_effect": payload.get("expected_effect", ""),
        }

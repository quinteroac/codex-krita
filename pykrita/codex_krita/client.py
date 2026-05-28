import base64
import binascii
import json
import math
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from .app_server import AppServerClient, local_image_input, skill_input, text_input
from .image_bridge import (
    TRANSPARENCY_OPAQUE,
    TRANSPARENCY_PRESERVE_ALPHA,
    TRANSPARENCY_REMOVE_FLAT_BACKGROUND,
)
from .script_runner import validate_script_code
from .setup import find_codex_binary


SCRIPT_SYSTEM_PROMPT = """You generate Python scripts for Krita.
Return only JSON with keys: code, reason, expected_effect.
The code runs inside Krita's Python environment with `from krita import *` available.
Avoid destructive file operations. Prefer creating new layers or reversible document changes.
"""

ANIMATION_PLAN_SYSTEM_PROMPT = """You are planning animation work for Krita.
Return only JSON with keys: summary, frames, notes.
The plan must be practical for a 2D artist using Krita's timeline.
Keep steps semi-guided and non-destructive by default.
"""

IMAGEGEN_SKILL_PATH = os.path.expanduser(
    os.environ.get("KRITA_CODEX_IMAGEGEN_SKILL", "~/.codex/skills/.system/imagegen")
)


class CodexDirectClient:
    """Direct in-process client for Krita's worker thread.

    This talks to the local Codex SDK/app-server. It does not use the OpenAI API
    SDK directly and does not read OPENAI_API_KEY.
    """

    def __init__(self, model="gpt-5.4"):
        self.model = model
        self.activity_callback = None

    def set_activity_callback(self, callback):
        self.activity_callback = callback

    def _activity(self, message):
        if self.activity_callback:
            self.activity_callback(message)

    def call(self, method, params=None):
        params = params or {}
        if method == "analyze_image":
            return self.analyze_image(
                params.get("image_path"),
                params.get("question", ""),
            )
        if method == "generate_image":
            return self.generate_image(
                params["prompt"],
                params.get("size", "1024x1024"),
                params.get("quality", "medium"),
                params.get("transparency_mode", TRANSPARENCY_OPAQUE),
                params.get("image_path"),
                params.get("context_scope"),
            )
        if method == "edit_image":
            return self.edit_image(
                params["prompt"],
                params.get("image_path"),
                params.get("mask_path"),
                params.get("size", "1024x1024"),
                params.get("quality", "medium"),
                params.get("inpaint_padding", 0),
                params.get("blend_feather", 0),
            )
        if method == "propose_script":
            return self.propose_script(
                params["task"],
                params.get("document_context") or {},
            )
        if method == "propose_animation_plan":
            return self.propose_animation_plan(
                params["task"],
                params.get("document_context") or {},
                params.get("animation_context") or {},
            )
        if method == "generate_animation_frame":
            return self.generate_animation_frame(
                params["prompt"],
                params.get("plan_text", ""),
                params.get("mode", "storyboard"),
                params.get("target_frame", 0),
                params.get("start_frame", 0),
                params.get("end_frame", 0),
                params.get("frame_count", 1),
                params.get("quality", "medium"),
                params.get("transparency_mode", TRANSPARENCY_PRESERVE_ALPHA),
                params.get("image_path"),
                params.get("image_refs"),
                params.get("context_scope"),
                params.get("animation_context") or {},
            )
        if method == "generate_animation_sheet":
            return self.generate_animation_sheet(
                params["prompt"],
                params.get("plan_text", ""),
                params.get("mode", "storyboard"),
                params.get("start_frame", 0),
                params.get("end_frame", 0),
                params.get("frame_count", 1),
                params.get("quality", "medium"),
                params.get("transparency_mode", TRANSPARENCY_PRESERVE_ALPHA),
                params.get("image_path"),
                params.get("context_scope"),
                params.get("animation_context") or {},
            )
        if method == "validate_script":
            validate_script_code(params["code"])
            return {"valid": True}
        raise RuntimeError("Unknown method: %s" % method)

    def _run_codex(self, prompt):
        codex_bin = find_codex_binary()
        with AppServerClient(codex_bin, model=self.model) as codex:
            thread_id = codex.thread_start()
            result = self._run_turn_stream(codex, thread_id, prompt)
        return result.final_response

    def _imagegen_skill_input(self):
        if Path(IMAGEGEN_SKILL_PATH).exists():
            return skill_input("imagegen", str(IMAGEGEN_SKILL_PATH))
        return None

    def _run_codex_with_imagegen(self, text, image_path=None, mask_path=None, image_refs=None):
        codex_bin = find_codex_binary()
        inputs = []
        skill = self._imagegen_skill_input()
        if skill is not None:
            inputs.append(skill)
        else:
            text = "Use the imagegen skill if available.\n\n" + text
        inputs.append(text_input(text))
        if image_refs:
            for ref in image_refs:
                path = ref.get("path")
                if not path:
                    continue
                inputs.append(
                    text_input(
                        "Animation reference image follows: %s, frame %s."
                        % (ref.get("label") or "reference", ref.get("frame"))
                    )
                )
                inputs.append(local_image_input(path))
        elif image_path:
            inputs.append(local_image_input(image_path))
        if mask_path:
            inputs.append(
                text_input(
                    "Inpainting mask image follows. Transparent pixels are the selected editable area. "
                    "Opaque pixels must be preserved from the base image. Use this attached image as visual mask input only; "
                    "do not inspect, transform, or postprocess the mask file with shell commands."
                )
            )
            inputs.append(local_image_input(mask_path))

        with AppServerClient(codex_bin, model=self.model) as codex:
            thread_id = codex.thread_start()
            return self._run_turn_stream(codex, thread_id, inputs)

    def analyze_image(self, image_path, question):
        prompt = "\n".join(
            [
                "Analyze this Krita artwork using Codex's multimodal capabilities.",
                "User request: %s" % (question or "Give concrete artistic and technical feedback."),
                "Return concise, actionable feedback for the artist.",
            ]
        )
        codex_bin = find_codex_binary()
        with AppServerClient(codex_bin, model=self.model) as codex:
            thread_id = codex.thread_start()
            result = self._run_turn_stream(
                codex,
                thread_id,
                [text_input(prompt), local_image_input(image_path)],
            )
        return {"text": result.final_response}

    def generate_image(
        self,
        prompt,
        size="1024x1024",
        quality="medium",
        transparency_mode=TRANSPARENCY_OPAQUE,
        image_path=None,
        context_scope=None,
    ):
        size_instruction = self._size_instruction(size, "active Krita document")
        transparency_instruction = self._generation_transparency_instruction(transparency_mode)
        context_instruction = self._generation_context_instruction(context_scope) if image_path else None
        codex_prompt = "\n".join(
            [line for line in [
                "Use Codex's image-generation capability for a Krita workflow.",
                "Create an image from this prompt:",
                prompt,
                context_instruction,
                size_instruction,
                "Quality: %s" % quality,
                transparency_instruction,
                "Always create an image artifact. Do not stop with a text-only answer just because a filesystem path is unavailable.",
                "If the runtime exposes a saved PNG path, return only JSON:",
                '{"image_path": "/absolute/path/to/generated.png", "text": "short summary"}',
                "If an image artifact exists but no filesystem path is exposed, return JSON with only a text field. The Krita plugin will read the image artifact from the SDK event stream.",
                "If image artifacts are not available at all, return JSON with only a text field explaining the limitation.",
            ] if line]
        )
        return self._parse_image_turn_result(self._run_codex_with_imagegen(codex_prompt, image_path=image_path))

    def _generation_context_instruction(self, context_scope):
        if context_scope == "active_layer":
            return (
                "A Krita active-layer reference image is attached. Use it as visual context for subject, style, "
                "composition, palette, lighting, and line/rendering language. Generate a new image that follows "
                "the user prompt while staying coherent with that layer."
            )
        if context_scope == "selection":
            return (
                "A crop of the selected Krita area is attached. Use it as visual reference for the requested generation. "
                "Respect its subject, style, palette, lighting, and composition cues unless the user explicitly asks to change them."
            )
        return (
            "A Krita document reference image is attached. Use it as visual context for subject, style, composition, "
            "palette, lighting, and perspective. Generate a new image that follows the user prompt while staying coherent with the document."
        )

    def _generation_transparency_instruction(self, transparency_mode):
        if transparency_mode == TRANSPARENCY_REMOVE_FLAT_BACKGROUND:
            return (
                "Output format: PNG. For isolated subjects, stickers, assets, cutouts, characters, props, or icons, "
                "use a perfectly flat solid #00ff00 chroma-key background if native transparency is not available. "
                "Do not use #00ff00 in the subject. No shadow, gradient, texture, floor plane, or lighting variation in the background."
            )
        if transparency_mode == TRANSPARENCY_PRESERVE_ALPHA:
            return "Output format: PNG with alpha channel when transparency is useful. Do not use chroma-key backgrounds."
        return "Output format: fully opaque PNG. Do not use transparency or chroma-key backgrounds."

    def edit_image(
        self,
        prompt,
        image_path,
        mask_path=None,
        size="1024x1024",
        quality="medium",
        inpaint_padding=0,
        blend_feather=0,
    ):
        size_instruction = self._size_instruction(size, "attached base image crop")
        codex_prompt = "\n".join(
            [
                "Use Codex's image-editing capability for a Krita workflow.",
                "Use only the attached base image crop and attached mask image as image inputs.",
                "Do not run shell commands, inspect local files, read image metadata manually, invoke external tools, or do PNG postprocessing.",
                "Krita will handle mask clipping, alpha feathering, and final layer composition after you return the edited image artifact.",
                "Edit request: %s" % prompt,
                "Use the mask as an inpainting mask: modify only transparent masked pixels and preserve opaque masked pixels from the base image.",
                "The editable mask may include %s px of padding around the user's original selection so the edit can complete forms instead of cutting them off." % inpaint_padding,
                "Krita will composite the returned image with about %s px of feathering, so match lighting, color, texture, perspective, and edge continuity with the unchanged image." % blend_feather,
                "Do not create a visibly separate pasted object. Avoid hard cutoffs at the original selection boundary.",
                size_instruction,
                "Quality: %s" % quality,
                "Output format: PNG image artifact matching the attached crop. Return the full edited crop; do not pre-clip it to the mask.",
                "If the runtime naturally exposes an absolute PNG path, include it in JSON. Do not run commands to find or create that path.",
                '{"image_path": "/absolute/path/to/edited.png", "text": "short summary"}',
                "If an image artifact exists but no path is exposed to you, return JSON with only a text field; the Krita plugin will read the image artifact from the SDK event stream.",
                "If image artifacts are not available in this Codex runtime, return JSON with only a text field explaining the limitation.",
            ]
        )
        return self._parse_image_turn_result(
            self._run_codex_with_imagegen(codex_prompt, image_path=image_path, mask_path=mask_path)
        )

    def _size_instruction(self, size, source_name):
        if isinstance(size, str) and size.startswith("auto:"):
            dimensions = size.split(":", 1)[1]
            try:
                width_text, height_text = dimensions.lower().split("x", 1)
                width = int(width_text)
                height = int(height_text)
                if width > 0 and height > 0:
                    divisor = math.gcd(width, height)
                    return (
                        "Size: auto, but preserve the %s aspect ratio: %sx%s (%s:%s). "
                        "Choose generated dimensions that match this ratio as closely as possible unless the user explicitly asks otherwise."
                        % (source_name, width, height, width // divisor, height // divisor)
                    )
            except Exception:
                pass
            return (
                "Size: auto, but preserve the %s aspect ratio from %s. "
                "Choose generated dimensions that match it as closely as possible unless the user explicitly asks otherwise."
                % (source_name, dimensions)
            )
        if size == "auto":
            return "Size: auto. Choose the most appropriate aspect ratio and dimensions for the request."
        return "Target size: %s" % size

    def propose_script(self, task, document_context):
        prompt = json.dumps(
            {
                "system": SCRIPT_SYSTEM_PROMPT,
                "task": task,
                "document_context": document_context,
            }
        )
        raw = self._run_codex(prompt).strip()
        payload = self._parse_json(raw)
        code = payload.get("code", "")
        validate_script_code(code)
        return {
            "code": code,
            "reason": payload.get("reason", ""),
            "expected_effect": payload.get("expected_effect", ""),
        }

    def propose_animation_plan(self, task, document_context, animation_context):
        prompt = json.dumps(
            {
                "system": ANIMATION_PLAN_SYSTEM_PROMPT,
                "task": task,
                "document_context": document_context,
                "animation_context": animation_context,
                "required_output": {
                    "summary": "one paragraph",
                    "frames": [
                        {
                            "frame": "integer frame number or range",
                            "purpose": "pose, breakdown, inbetween, cleanup, timing, or loop role",
                            "instruction": "what to draw or generate",
                        }
                    ],
                    "notes": ["short practical cautions"],
                },
            }
        )
        raw = self._run_codex(prompt).strip()
        payload = self._parse_json(raw)
        return {"plan": payload, "plan_text": self._format_animation_plan(payload, raw), "text": raw}

    def generate_animation_frame(
        self,
        prompt,
        plan_text="",
        mode="storyboard",
        target_frame=0,
        start_frame=0,
        end_frame=0,
        frame_count=1,
        quality="medium",
        transparency_mode=TRANSPARENCY_PRESERVE_ALPHA,
        image_path=None,
        image_refs=None,
        context_scope=None,
        animation_context=None,
    ):
        transparency_instruction = self._animation_transparency_instruction(transparency_mode)
        if image_refs:
            context_instruction = "The attached image is the numbered animation sheet reference layer generated by Plan + Sheet."
        else:
            context_instruction = self._animation_context_instruction(context_scope) if image_path else None
        target_size_instruction = self._animation_target_size_instruction(animation_context)
        codex_prompt = "\n".join(
            [line for line in [
                "Use Codex's image-generation capability for a Krita animation workflow.",
                "Create one PNG frame artifact for the requested animation step.",
                "Animation mode: %s" % mode,
                "Target frame: %s" % target_frame,
                "Frame range: %s to %s, requested count: %s" % (start_frame, end_frame, frame_count),
                "Artist request: %s" % prompt,
                "Existing animation plan:\n%s" % plan_text if plan_text else None,
                "Animation context JSON: %s" % json.dumps(animation_context or {}, sort_keys=True),
                "Only one animation reference image is attached: a numbered animation sheet.",
                "Analyze that sheet, find the panel labeled for target frame %s, and generate a fuller version of that same panel." % target_frame,
                "Use the sheet for pose, silhouette, composition, character identity, proportions, palette, camera, scale, ground line, and style continuity.",
                "Do not reproduce any numbers, labels, bands, borders, gutters, or text in the generated frame.",
                target_size_instruction,
                context_instruction,
                "Preserve the subject identity, palette, line language, camera, and proportions from the attached Krita reference unless the user explicitly asks for a change.",
                "For inbetweens, create a plausible intermediate pose rather than a full redesign. For loops, favor seamless timing and reusable silhouettes. For storyboard, favor readable staging.",
                "Quality: %s" % quality,
                transparency_instruction,
                "Always create an image artifact. Return only JSON when a saved PNG path is exposed:",
                '{"image_path": "/absolute/path/to/generated.png", "text": "short summary"}',
                "If image artifacts are not available at all, return JSON with only a text field explaining the limitation.",
            ] if line]
        )
        return self._parse_image_turn_result(
            self._run_codex_with_imagegen(codex_prompt, image_path=image_path, image_refs=image_refs)
        )

    def generate_animation_sheet(
        self,
        prompt,
        plan_text="",
        mode="storyboard",
        start_frame=0,
        end_frame=0,
        frame_count=1,
        quality="medium",
        transparency_mode=TRANSPARENCY_PRESERVE_ALPHA,
        image_path=None,
        context_scope=None,
        animation_context=None,
    ):
        transparency_instruction = self._animation_transparency_instruction(transparency_mode)
        context_instruction = self._animation_context_instruction(context_scope) if image_path else None
        count = max(1, int(frame_count))
        target_size_instruction = self._animation_target_size_instruction(animation_context)
        codex_prompt = "\n".join(
            [line for line in [
                "Use Codex's image-generation capability for a Krita animation planning workflow.",
                "Create one single horizontal animation contact sheet PNG, not separate images.",
                "The sheet must contain exactly %s equal-width panels in one row." % count,
                "Each artwork panel should represent the same canvas aspect ratio as the final animation frame.",
                "Do not include any numbers, labels, text, arrows, gutters, borders, captions, UI marks, or label bands anywhere in the image.",
                "Keep every character or moving subject fully inside its panel with at least 8 percent empty safe padding from each panel edge. Do not crop hands, feet, head, props, shadows, or motion arcs.",
                "Each artwork panel is a rough but coherent thumbnail/key pose for the animation sequence from frame %s to frame %s." % (start_frame, end_frame),
                "Animation mode: %s" % mode,
                "Artist request: %s" % prompt,
                "Animation plan:\n%s" % plan_text if plan_text else None,
                "Animation context JSON: %s" % json.dumps(animation_context or {}, sort_keys=True),
                context_instruction,
                "Prioritize consistency across the whole strip: same character identity, proportions, costume, palette, camera, scale, ground line, and drawing style in every panel.",
                "Make the pose progression readable across the strip. This sheet will be inserted into Krita as a reference layer and used as the only image reference for later full-frame generation.",
                "Use simple rough animation thumbnails, not final cleanup. Do not redesign between panels.",
                target_size_instruction,
                "Quality: %s" % quality,
                transparency_instruction,
                "Always create an image artifact. Return only JSON when a saved PNG path is exposed:",
                '{"image_path": "/absolute/path/to/animation_sheet.png", "text": "short summary"}',
                "If image artifacts are not available at all, return JSON with only a text field explaining the limitation.",
            ] if line]
        )
        return self._parse_image_turn_result(self._run_codex_with_imagegen(codex_prompt, image_path=image_path))

    def _animation_target_size_instruction(self, animation_context):
        width = (animation_context or {}).get("width")
        height = (animation_context or {}).get("height")
        if width and height:
            return (
                "Final frame size must be exactly %sx%s pixels. Keep every generated frame at this same size and aspect ratio."
                % (int(width), int(height))
            )
        return "Keep every generated frame at the same size and aspect ratio as the active Krita document."

    def _animation_transparency_instruction(self, transparency_mode):
        if transparency_mode == TRANSPARENCY_OPAQUE:
            return "Output format: fully opaque PNG. Preserve or create a background only if it is part of the animation frame."
        if transparency_mode == TRANSPARENCY_REMOVE_FLAT_BACKGROUND:
            return (
                "Output format: PNG animation asset with a removable flat background. Prefer real alpha transparency. "
                "If native alpha is unavailable, use a perfectly flat solid #00ff00 chroma-key background and do not use #00ff00 in the drawing. "
                "No paper texture, grey canvas, shadow, gradient, border, floor plane, or lighting variation in the background."
            )
        return (
            "Output format: PNG with real alpha transparency. The animation drawing must be on a transparent background. "
            "Do not include a white, grey, paper, checkerboard, studio, or canvas background unless the user explicitly asks for one."
        )

    def _animation_context_instruction(self, context_scope):
        if context_scope == "active_layer":
            return (
                "A Krita active-layer reference image is attached. Use it as the visual source for this animation frame."
            )
        if context_scope == "selection":
            return (
                "A Krita selection crop is attached. Use it as the visual source for this animation frame."
            )
        return "A full Krita document reference image is attached. Use it as visual continuity for this animation frame."

    def _format_animation_plan(self, payload, raw):
        if not isinstance(payload, dict) or "text" in payload:
            return raw
        lines = []
        summary = payload.get("summary")
        if summary:
            lines.append(str(summary))
        frames = payload.get("frames")
        if isinstance(frames, list):
            for frame in frames:
                if not isinstance(frame, dict):
                    lines.append("- %s" % frame)
                    continue
                lines.append(
                    "- Frame %s: %s - %s"
                    % (
                        frame.get("frame", "?"),
                        frame.get("purpose", "step"),
                        frame.get("instruction", ""),
                    )
                )
        notes = payload.get("notes")
        if isinstance(notes, list) and notes:
            lines.append("Notes: %s" % "; ".join(str(note) for note in notes))
        return "\n".join(lines) if lines else raw

    def _parse_image_result(self, raw):
        payload = self._parse_json(raw)
        return {
            "image_path": payload.get("image_path"),
            "text": payload.get("text", raw),
        }

    def _run_turn_stream(self, codex, thread_id, turn_input):
        self._activity("Codex: starting turn")
        turn_id = codex.turn_start(thread_id, turn_input)
        items = []
        usage = None
        completed_turn = None
        event_count = 0

        for event in codex.turn_stream(turn_id):
            event_count += 1
            method = getattr(event, "method", "")
            payload = getattr(event, "payload", None)
            self._emit_event_activity(method, payload)

            if method == "item/completed" and payload is not None:
                item = getattr(payload, "item", None)
                if item is not None:
                    items.append(item)
                continue
            if method == "thread/tokenUsage/updated" and payload is not None:
                usage = getattr(payload, "token_usage", None)
                continue
            if method == "turn/completed" and payload is not None:
                completed_turn = getattr(payload, "turn", None)

        if completed_turn is None:
            raise RuntimeError("Codex stream ended without turn/completed.")

        status = getattr(completed_turn, "status", None)
        status_value = getattr(status, "value", status)
        self._activity("Codex: completed turn status=%s events=%s" % (status_value, event_count))

        if status_value == "failed":
            error = getattr(completed_turn, "error", None)
            message = getattr(error, "message", None) or "Codex turn failed."
            raise RuntimeError(message)

        return SimpleNamespace(
            id=getattr(completed_turn, "id", None),
            status=status,
            error=getattr(completed_turn, "error", None),
            final_response=self._final_assistant_response_from_items(items),
            items=items,
            usage=usage,
        )

    def _emit_event_activity(self, method, payload):
        if method == "turn/started":
            turn = getattr(payload, "turn", None)
            self._activity("Codex: turn started %s" % (getattr(turn, "id", "") if turn else ""))
            return
        if method == "item/agentMessage/delta":
            delta = getattr(payload, "delta", "")
            if delta:
                self._activity("assistant delta: %s" % delta)
            return
        if method == "item/completed":
            item = getattr(payload, "item", None)
            root = item.root if hasattr(item, "root") else item
            item_type = getattr(root, "type", None)
            if item_type == "agentMessage":
                text = self._shorten(getattr(root, "text", ""), 240)
                self._activity("assistant: %s" % text)
                return
            if item_type == "imageGeneration":
                self._activity(
                    "imageGeneration: status=%s saved_path=%s result=%s"
                    % (
                        getattr(root, "status", None),
                        getattr(root, "saved_path", None),
                        self._shorten(getattr(root, "result", None), 120),
                    )
                )
                return
            self._activity("item completed: %s" % item_type)
            return
        if method == "thread/tokenUsage/updated":
            usage = getattr(payload, "token_usage", None)
            if usage is not None:
                self._activity("token usage updated")
            return
        if method == "turn/completed":
            turn = getattr(payload, "turn", None)
            status = getattr(getattr(turn, "status", None), "value", getattr(turn, "status", None))
            self._activity("Codex: turn completed status=%s" % status)
            return
        if method:
            self._activity("event: %s" % method)

    def _final_assistant_response_from_items(self, items):
        fallback = None
        for item in reversed(items):
            root = item.root if hasattr(item, "root") else item
            if getattr(root, "type", None) != "agentMessage":
                continue
            text = getattr(root, "text", None)
            phase = getattr(getattr(root, "phase", None), "value", getattr(root, "phase", None))
            if phase == "final_answer":
                return text
            if fallback is None:
                fallback = text
        return fallback

    def _parse_image_turn_result(self, turn_result):
        image_items = []
        for item in getattr(turn_result, "items", []):
            root = item.root if hasattr(item, "root") else item
            if getattr(root, "type", None) == "imageGeneration":
                image_items.append(root)

        for item in image_items:
            saved_path = getattr(item, "saved_path", None)
            if saved_path and os.path.exists(str(saved_path)):
                return {
                    "image_path": str(saved_path),
                    "text": getattr(item, "revised_prompt", None) or "Image generated.",
                }

            result = getattr(item, "result", None)
            path = self._image_result_to_path(result)
            if path:
                return {
                    "image_path": path,
                    "text": getattr(item, "revised_prompt", None) or "Image generated.",
                }

        final_response = getattr(turn_result, "final_response", None) or ""
        parsed = self._parse_image_result(final_response)
        if parsed.get("image_path"):
            return parsed

        if image_items:
            details = []
            for item in image_items:
                details.append(
                    "imageGeneration status=%s saved_path=%s result=%s"
                    % (
                        getattr(item, "status", None),
                        getattr(item, "saved_path", None),
                        self._shorten(getattr(item, "result", None)),
                    )
                )
            return {
                "image_path": None,
                "text": "Codex generated an image item, but the SDK did not expose a saved PNG path.\n"
                + "\n".join(details)
                + ("\n\n" + final_response if final_response else ""),
            }

        return {
            "image_path": None,
            "text": final_response or "No image artifact was returned by Codex.",
        }

    def _image_result_to_path(self, result):
        if not result:
            return None

        text = str(result)
        if os.path.exists(text):
            return text

        if text.startswith("file://"):
            path = text.removeprefix("file://")
            if os.path.exists(path):
                return path

        if text.startswith("data:image/"):
            try:
                header, encoded = text.split(",", 1)
            except ValueError:
                return None
            suffix = ".png"
            if "image/jpeg" in header:
                suffix = ".jpg"
            return self._write_image_bytes(base64.b64decode(encoded), suffix)

        try:
            decoded = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            return None
        if decoded.startswith(b"\x89PNG\r\n\x1a\n"):
            return self._write_image_bytes(decoded, ".png")
        if decoded.startswith(b"\xff\xd8\xff"):
            return self._write_image_bytes(decoded, ".jpg")
        return None

    def _write_image_bytes(self, data, suffix):
        handle = tempfile.NamedTemporaryFile(prefix="krita-codex-image-", suffix=suffix, delete=False)
        path = handle.name
        with handle:
            handle.write(data)
        return path

    def _shorten(self, value, limit=160):
        if value is None:
            return None
        text = str(value)
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def _parse_json(self, raw):
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.removeprefix("json").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": raw}

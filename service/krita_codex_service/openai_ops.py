from __future__ import annotations

import base64
import io
from typing import Any

from .protocol import image_data_url


class OpenAIOps:
    def __init__(self, model: str = "gpt-5.5") -> None:
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError("The openai package is not installed.") from exc

        self._client = OpenAI()
        self._model = model

    def analyze_image(self, image_b64: str, question: str, mime_type: str = "image/png") -> dict[str, Any]:
        response = self._client.responses.create(
            model=self._model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": question or "Analyze this Krita artwork and suggest concrete improvements.",
                        },
                        {
                            "type": "input_image",
                            "image_url": image_data_url(image_b64, mime_type),
                        },
                    ],
                }
            ],
        )
        return {"text": getattr(response, "output_text", "")}

    def generate_image(self, prompt: str, size: str = "1024x1024", quality: str = "medium") -> dict[str, Any]:
        response = self._client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size=size,
            quality=quality,
        )
        image_b64 = response.data[0].b64_json
        return {"image_b64": image_b64, "mime_type": "image/png"}

    def edit_image(
        self,
        prompt: str,
        image_b64: str,
        mask_b64: str | None,
        size: str = "1024x1024",
        quality: str = "medium",
    ) -> dict[str, Any]:
        image_file = io.BytesIO(base64.b64decode(image_b64))
        image_file.name = "krita-context.png"
        kwargs: dict[str, Any] = {
            "model": "gpt-image-1",
            "prompt": prompt,
            "image": image_file,
            "size": size,
            "quality": quality,
        }
        if mask_b64:
            mask_file = io.BytesIO(base64.b64decode(mask_b64))
            mask_file.name = "krita-mask.png"
            kwargs["mask"] = mask_file

        response = self._client.images.edit(**kwargs)
        return {"image_b64": response.data[0].b64_json, "mime_type": "image/png"}

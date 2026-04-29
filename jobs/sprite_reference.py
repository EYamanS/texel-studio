"""Handler for `sprite.reference` — generate a concept-art reference image."""

from __future__ import annotations

import base64
import io
import time
from typing import Iterator, Optional

from pydantic import BaseModel

from . import Event, JobContext, JobHandler, error, log, register_job, result


class SpriteReferenceParams(BaseModel):
    prompt: str
    feedback: Optional[str] = None
    model: Optional[str] = None
    sprite_type: str = "block"


@register_job("sprite.reference")
class SpriteReferenceHandler(JobHandler):
    Params = SpriteReferenceParams

    def run(self, params: SpriteReferenceParams, ctx: JobContext) -> Iterator[Event]:
        # One-shot — no streaming pixels here. We still yield events so the
        # dispatcher and worker contract is uniform across all kinds.
        from server import (
            DEFAULT_IMAGE_MODEL,
            IMAGE_GEN_MODELS,
            SPRITE_TYPES,
            gemini,
        )
        import storage
        from google import genai

        type_config = SPRITE_TYPES.get(params.sprite_type, SPRITE_TYPES["block"])
        ref_prompt = f"{params.prompt}\n\n{type_config['ref_prompt']}"
        if params.feedback:
            ref_prompt += f"\n\nRevision feedback: {params.feedback}"

        img_model = params.model if params.model in IMAGE_GEN_MODELS else DEFAULT_IMAGE_MODEL
        yield log(f"Generating reference with {img_model}", step="start")

        try:
            try:
                response = gemini().models.generate_content(
                    model=img_model,
                    contents=[ref_prompt],
                    config=genai.types.GenerateContentConfig(
                        response_modalities=["Image", "Text"],
                    ),
                )
            except Exception:
                response = gemini().models.generate_content(
                    model=img_model,
                    contents=[ref_prompt],
                )
        except Exception as e:
            yield error(f"Reference generation failed: {e}")
            return

        def _save_ref_part(part) -> str:
            rid = f"ref_{int(time.time())}_{hash(params.prompt) & 0xFFFF:04x}.png"
            try:
                buf = io.BytesIO()
                part.as_image().save(buf, format="PNG")
                storage.save_file(f"references/{rid}", buf.getvalue())
            except Exception:
                img_bytes = part.inline_data.data
                if isinstance(img_bytes, str):
                    img_bytes = base64.b64decode(img_bytes)
                storage.save_file(f"references/{rid}", img_bytes)
            return rid

        ref_id: Optional[str] = None
        for part in response.parts or []:
            if getattr(part, "inline_data", None) is not None:
                ref_id = _save_ref_part(part)
                break

        if ref_id is None and getattr(response, "candidates", None):
            for candidate in response.candidates:
                if getattr(candidate, "content", None):
                    for part in candidate.content.parts:
                        if getattr(part, "inline_data", None):
                            ref_id = _save_ref_part(part)
                            break
                    if ref_id:
                        break

        if not ref_id:
            yield error("No image in response. Model may not support image generation.")
            return

        yield log("Reference saved", step="complete")
        yield result(reference_id=ref_id, status="completed")

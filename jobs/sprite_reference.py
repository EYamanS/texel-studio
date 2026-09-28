"""Handler for `sprite.reference` — generate a concept-art reference image."""

from __future__ import annotations

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
            create_reference,
        )

        img_model = params.model if params.model in IMAGE_GEN_MODELS else DEFAULT_IMAGE_MODEL
        yield log(f"Generating reference with {img_model}", step="start")

        try:
            ref_id = create_reference(
                params.prompt,
                feedback=params.feedback,
                model=img_model,
                sprite_type=params.sprite_type,
            )
        except Exception as e:
            yield error(f"Reference generation failed: {e}")
            return

        yield log("Reference saved", step="complete")
        yield result(reference_id=ref_id, status="completed")

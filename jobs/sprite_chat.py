"""Handler for `sprite.chat` — continue editing an existing sprite via chat."""

from __future__ import annotations

from typing import Iterator, Optional

from pydantic import BaseModel, Field

from . import Event, JobContext, JobHandler, log, progress, result, register_job
from ._runtime import EventBridge, run_in_thread


class SpriteChatParams(BaseModel):
    parent_job_id: str                                   # the sprite.generate job we're editing
    message: str
    colors: list[str] = Field(default_factory=lambda: ["#c8a44e"])
    size: int = 16
    model: Optional[str] = None
    sprite_type: str = "block"
    system_prompt: Optional[str] = None
    pixel_data: Optional[list[list[int]]] = None         # current canvas state


@register_job("sprite.chat")
class SpriteChatHandler(JobHandler):
    Params = SpriteChatParams

    def run(self, params: SpriteChatParams, ctx: JobContext) -> Iterator[Event]:
        from agent import run_agent_stream
        from server import (
            DEFAULT_MODEL,
            DEFAULT_SYSTEM_PROMPT,
            upscale_image,
        )
        import storage

        size = params.size
        model = params.model or DEFAULT_MODEL
        system_prompt = params.system_prompt or DEFAULT_SYSTEM_PROMPT
        # Chat continuations key the LangGraph thread on the parent job — that's
        # how the agent's conversation history is preserved across edits.
        gen_id = params.parent_job_id

        bridge = EventBridge()
        bridge.emit(log(f"Editing: {params.message[:100]}...", step="chat"))

        step_count = [0]
        last_pixel_step = [0]

        def on_step(canvas, step_type, msg):
            step_count[0] += 1
            bridge.emit(log(msg, step=f"{step_type}_{step_count[0]}"))
            if step_type == "tool_result" and (step_count[0] - last_pixel_step[0] >= 1):
                last_pixel_step[0] = step_count[0]
                bridge.emit(progress(
                    pixel_data=[row[:] for row in canvas.pixels],
                    iteration=step_count[0],
                    notes=f"Step {step_count[0]}",
                ))

        def worker():
            canvas = run_agent_stream(
                gen_id=gen_id,
                message=params.message,
                palette=params.colors,
                size=size,
                model_name=model,
                style_prompt=system_prompt,
                sprite_type=params.sprite_type,
                reference_b64=None,
                on_step=on_step,
                cancel_check=ctx.cancel_check,
                existing_pixels=params.pixel_data,
            )

            final_pixels = [row[:] for row in canvas.pixels]
            bridge.emit(progress(
                pixel_data=final_pixels,
                iteration=step_count[0],
                notes="Edit finished",
            ))

            final_img = canvas.to_image()
            external_id = ctx.external_id or ctx.job_id
            filename = f"gen_{external_id}_{size}x{size}.png"
            storage.save_image(final_img, f"output/{filename}")
            storage.save_image(upscale_image(final_img, 512), f"output/gen_{external_id}_preview.png")

            bridge.emit(log(f"Edit done in {step_count[0]} steps", step="complete"))
            bridge.emit(result(
                id=external_id,
                image_path=filename,
                iterations=step_count[0],
                pixel_data=final_pixels,
                parent_job_id=gen_id,
                status="completed",
            ))

        run_in_thread(worker, bridge)
        yield from bridge.iter_events()

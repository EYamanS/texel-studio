"""Handler for `sprite.from_photo` — quantize a user-uploaded photo to the
selected palette to produce a pixel-art sprite.

Pipeline:
  1. Download the image from `image_url` (a Supabase Storage signed URL).
  2. Convert to RGB and resize to `size x size`. We let PIL pick a sensible
     downsampler — for large images this is `LANCZOS`, which preserves
     detail before quantizing, then we clamp to the palette.
  3. For each output pixel, snap RGB to the nearest palette color by
     Euclidean distance. (Lab would be perceptually nicer but adds a dep;
     RGB-distance is the right starting point for a feature shipping today.)
  4. Save the rendered PNG and return pixel_data.

This handler proves the abstraction works: zero changes to the dispatcher,
the worker, or the cloud API are needed to add it. The cloud just calls
POST /api/jobs with kind="sprite.from_photo".
"""

from __future__ import annotations

import io
import urllib.request
from typing import Iterator, Optional

from PIL import Image
from pydantic import BaseModel, Field

from . import Event, JobContext, JobHandler, log, progress, register_job, result
from ._runtime import EventBridge, run_in_thread


class SpriteFromPhotoParams(BaseModel):
    image_url: str
    colors: list[str] = Field(default_factory=lambda: ["#000000", "#ffffff"])
    size: int = 32


@register_job("sprite.from_photo")
class SpriteFromPhotoHandler(JobHandler):
    Params = SpriteFromPhotoParams

    def run(self, params: SpriteFromPhotoParams, ctx: JobContext) -> Iterator[Event]:
        from server import upscale_image
        import storage

        external_id = ctx.external_id or ctx.job_id
        bridge = EventBridge()

        def worker() -> None:
            bridge.emit(log("Downloading image...", step="download"))
            img_bytes = _download_image(params.image_url)

            bridge.emit(log(f"Resizing to {params.size}×{params.size}...", step="resize"))
            src = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            small = src.resize((params.size, params.size), Image.Resampling.LANCZOS)

            bridge.emit(log(f"Quantizing to {len(params.colors)} palette colors...", step="quantize"))
            palette_rgb = [_hex_to_rgb(c) for c in params.colors]
            pixel_data: list[list[int]] = [
                [_nearest_index(small.getpixel((x, y)), palette_rgb) for x in range(params.size)]
                for y in range(params.size)
            ]

            # Render the quantized canvas via the same code path sprite.generate uses.
            bridge.emit(progress(pixel_data=pixel_data, iteration=1, notes="Quantized"))

            # Build PIL image directly from pixel_data -> palette.
            out = Image.new("RGBA", (params.size, params.size), (0, 0, 0, 0))
            for y, row in enumerate(pixel_data):
                for x, idx in enumerate(row):
                    if 0 <= idx < len(palette_rgb):
                        r, g, b = palette_rgb[idx]
                        out.putpixel((x, y), (r, g, b, 255))

            filename = f"gen_{external_id}_{params.size}x{params.size}.png"
            storage.save_image(out, f"output/{filename}")
            storage.save_image(upscale_image(out, 512), f"output/gen_{external_id}_preview.png")

            bridge.emit(log("Done", step="complete"))
            bridge.emit(result(
                id=external_id,
                image_path=filename,
                iterations=1,
                pixel_data=pixel_data,
                status="completed",
            ))

        run_in_thread(worker, bridge)
        yield from bridge.iter_events()


# ── Helpers ──

def _download_image(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "texel-studio/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _nearest_index(rgb: tuple[int, int, int] | tuple[int, ...], palette: list[tuple[int, int, int]]) -> int:
    r, g, b = rgb[0], rgb[1], rgb[2]
    best = 0
    best_d2 = 1 << 30
    for i, (pr, pg, pb) in enumerate(palette):
        d2 = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best = i
            if d2 == 0:
                break
    return best

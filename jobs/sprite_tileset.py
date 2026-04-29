"""Handler for `sprite.tileset` — generate the 16 autotile variants from a sprite."""

from __future__ import annotations

from typing import Iterator

from pydantic import BaseModel

from . import Event, JobContext, JobHandler, log, register_job, result


class SpriteTilesetParams(BaseModel):
    name: str                          # filename prefix, e.g. "Dirt" → Dirt_00.png..Dirt_15.png
    pixel_data: list[list[int]]
    palette: list[str]
    size: int


@register_job("sprite.tileset")
class SpriteTilesetHandler(JobHandler):
    Params = SpriteTilesetParams

    def run(self, params: SpriteTilesetParams, ctx: JobContext) -> Iterator[Event]:
        from pathlib import Path
        from server import OUTPUT_DIR, generate_tileset, pixels_to_image

        yield log("Building base image...", step="start")
        base_img = pixels_to_image(params.pixel_data, params.palette, params.size)

        yield log("Generating 16 variants...", step="variants")
        variants = generate_tileset(base_img)

        tileset_dir = Path(OUTPUT_DIR) / "tilesets" / params.name
        tileset_dir.mkdir(parents=True, exist_ok=True)

        files = []
        for mask in range(16):
            filename = f"{params.name}_{mask:02d}.png"
            variants[mask].save(tileset_dir / filename)
            files.append(filename)

        yield log(f"Wrote {len(files)} files", step="complete")
        yield result(
            name=params.name,
            path=str(tileset_dir),
            files=files,
            count=len(files),
            status="completed",
        )

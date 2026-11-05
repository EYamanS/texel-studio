"""
Batch mode, color variants and shipping files into a game project.

A batch file holds many designs; one command builds, checks and ships all of them and writes ONE overview picture:

    @design sword size=32 ship=assets/sprites/sword.png
    ...operations...
    @design card_common size=52x72 on=assets/card_bg.png at=8,15 fit=36
    ...operations...

Header options (after the name):
    size=32 | size=52x72        canvas (WxH = usable rectangle)
    colors=#111,#fff | none     start palette; `none` (default) = colours are added as you paint
    ship=path/to/file.png       write the PNG there (an existing file is backed up to paint_work/ship_backup/)
    on=base.png|gNN             show the design placed on this image in the overview (a card, a tile ...)
    at=x,y  fit=N               position (default centred) and size in px for that mock-up
    lint=0                      skip the quality check
Re-running a batch overwrites designs with the same name instead of creating new ones.
"""

import os
import re
import shutil
import time
from pathlib import Path

from texel_paint import colors as C
from texel_paint import imaging, store
from texel_paint.lint import lint
from texel_paint.painter import apply_ops
from texel_paint.script import parse_ops, tokenize


def parse_size(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)(?:x(\d+))?", str(text))
    if not match:
        raise ValueError(f"Size '{text}' not understood (e.g. 32 or 52x72)")
    w = int(match.group(1))
    return w, int(match.group(2) or w)


# ───────────────────────── Variants ─────────────────────────

def variant(gid: int, name: str, pairs: dict | None = None, hue: float = 0.0, sat: float = 1.0,
            light: float = 0.0, only: list[str] | None = None) -> int:
    """Copy of a design with a recoloured palette. `pairs` maps exact colours ({old: new}); otherwise hue (degrees),
    sat (multiplier) and light (delta) shift every colour (or just those in `only`). Perfect for rarity/team colours."""
    canvas = store.load(gid)
    mapping = {C.norm_hex(k): C.norm_hex(v) for k, v in (pairs or {}).items()}
    restrict = {C.norm_hex(o) for o in (only or [])}
    palette = []
    for colour in canvas.palette:
        h = C.norm_hex(colour)
        if h in mapping:
            palette.append(mapping[h])
        elif (not restrict or h in restrict) and (hue or sat != 1.0 or light):
            palette.append(C.shift_color(h, hue, sat, light))
        else:
            palette.append(h)
    new_id = store.create(name, canvas.size, "item", palette, pixels=[r[:] for r in canvas.pixels],
                          width=canvas.width, height=canvas.height)
    store.save(new_id, store.load(new_id), f"variant of {gid}")
    return new_id


# ───────────────────────── Shipping ─────────────────────────

def ship_path(target: str) -> Path:
    path = Path(target)
    root = os.environ.get("TEXEL_SHIP_ROOT")
    return path if path.is_absolute() or not root else Path(root) / path


def ship(gid: int, target: str, dry: bool = False) -> str:
    """Write the design as PNG to `target` (relative to TEXEL_SHIP_ROOT if set). An existing file is first copied to
    paint_work/ship_backup/ so nothing is ever lost."""
    destination = ship_path(target)
    canvas = store.load(gid)
    image = canvas.to_image()
    if not canvas.is_rect:
        bbox = image.getbbox()
        if bbox and (bbox[2] - bbox[0], bbox[3] - bbox[1]) != image.size:
            image = image.crop(bbox)
    if dry:
        return f"(dry run) {destination} <- {image.width}x{image.height}"
    if destination.exists():
        backup = store.WORK / "ship_backup"
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, backup / f"{destination.stem}_{time.strftime('%Y%m%d_%H%M%S')}{destination.suffix}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    return f"{destination} ({image.width}x{image.height})"


# ───────────────────────── Batch ─────────────────────────

def _prepare(name: str, w: int, h: int, colors: list[str]) -> int:
    """Existing design of this name (same canvas size) is reset and reused, otherwise a new one is created."""
    size = max(w, h)
    existing = store.find_by_name(name, size)
    canvas = store.PaintCanvas(size, list(colors), width=w, height=h)
    if existing:
        store.reset(existing, canvas, "batch reset")
        return existing
    gid = store.create(name, size, "item", list(colors), width=w, height=h)
    store.save(gid, store.load(gid), "batch created")
    return gid


def run_batch(spec: str, dry: bool = False) -> tuple[list[str], Path]:
    """Build all designs of a batch file. Returns (report lines, overview image path)."""
    blocks, current = [], None
    for raw in spec.splitlines():
        if raw.startswith("@design "):
            current = {"head": tokenize(raw[8:]), "ops": []}
            blocks.append(current)
        elif current is not None:
            current["ops"].append(raw)
    if not blocks:
        raise ValueError("No '@design' blocks found")
    lines, items = [], []
    for block in blocks:
        name = block["head"][0]
        options = dict(t.split("=", 1) for t in block["head"][1:] if "=" in t)
        w, h = parse_size(options.get("size", "32"))
        colors_option = options.get("colors", "none")
        colors = [] if colors_option in ("none", "auto", "") else [C.norm_hex(x) for x in colors_option.split(",")]
        gid = _prepare(name, w, h, colors)
        canvas = store.load(gid)
        try:
            ops = parse_ops("\n".join(block["ops"]))
        except Exception as exc:                          # a typo in one script must not stop the others
            lines.append(f"{name} g{gid} ERROR | script: {exc}")
            continue
        errors, _ = apply_ops(canvas, ops)
        store.save(gid, canvas, f"batch {len(ops)} ops")
        summary, warnings = lint(canvas)
        status = "OK" if not errors and not warnings else "CHECK"
        shipped = ""
        if options.get("ship") and not errors:
            shipped = " -> " + ship(gid, options["ship"], dry)
        lines.append(f"{name} g{gid} {status} | {summary}{shipped}")
        lines += [f"   ERROR: {e}" for e in errors] + [f"   warning: {x}" for x in warnings]
        image = canvas.to_image()
        if options.get("on"):
            at = tuple(int(v) for v in options["at"].split(",")) if options.get("at") else None
            image = imaging.mockup(image, imaging.load_source(options["on"]), at,
                                   int(options["fit"]) if options.get("fit") else None)
        items.append((name, image, f"g{gid} {w}x{h} {status}"))
    out = store.WORK / "batch_sheet.png"
    store.ensure_dirs()
    if items:
        imaging.contact_sheet(items, columns=min(4, len(items))).convert("RGB").save(out)
        lines.append(f"overview: {out}")
    return lines, out

"""
Images: coordinate-ruler previews, ASCII dumps, reference comparison, export, layered compose, mock-ups and contact sheets.
Everything an agent needs to *judge* a design cheaply (numbers and one small image instead of many large ones).
"""

import base64
import io
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from texel_paint import colors as C
from texel_paint import store
from texel_paint.store import PaintCanvas


# ───────────────────────── Previews and dumps ─────────────────────────

def content_bbox(canvas: PaintCanvas):
    """(x1, y1, x2, y2) of all painted pixels inside the usable rectangle, or None."""
    points = [(x, y) for y in range(canvas.height) for x in range(canvas.width) if canvas.pixels[y][x] != -1]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def preview(canvas: PaintCanvas, path: str, scale: int | None = None, grid: bool = True, crop: bool = True,
            region=None, panels: bool = True) -> str:
    """Preview PNG with a coordinate ruler (absolute coordinates) and a 1x real-size panel on the right.
    Default: cropped to the content. region=(x1,y1,x2,y2) shows just that part, crop=False the whole rectangle."""
    width, height = canvas.width, canvas.height
    bbox = content_bbox(canvas)
    if region:
        x0, y0, x1, y1 = region
    elif crop and bbox:
        x0, y0, x1, y1 = max(0, bbox[0] - 1), max(0, bbox[1] - 1), min(width - 1, bbox[2] + 1), min(height - 1, bbox[3] + 1)
    else:
        x0, y0, x1, y1 = 0, 0, width - 1, height - 1
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width - 1, x1), min(height - 1, y1)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    scale = scale or max(4, min(24, 520 // max(w, h)))
    margin = 22
    panel = (w + 10) if panels else 0
    out = Image.new("RGB", (margin + w * scale + 6 + panel, margin + h * scale + 4), (28, 28, 34))
    draw, font = ImageDraw.Draw(out), ImageFont.load_default()

    def colour_at(x, y):
        idx = canvas.pixels[y][x]
        return C.to_rgb(canvas.palette[idx]) if 0 <= idx < len(canvas.palette) else None

    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            rgb = colour_at(x, y) or ((200, 200, 200) if (x + y) % 2 == 0 else (150, 150, 150))
            X, Y = margin + (x - x0) * scale, margin + (y - y0) * scale
            draw.rectangle([X, Y, X + scale - 1, Y + scale - 1], fill=rgb)
    step = 4 if scale >= 10 else 8
    if grid and scale >= 8:
        for x in range(x0, x1 + 2):
            X = margin + (x - x0) * scale
            draw.line([(X, margin), (X, margin + h * scale)], fill=(255, 255, 255) if x % step == 0 else (60, 60, 70))
        for y in range(y0, y1 + 2):
            Y = margin + (y - y0) * scale
            draw.line([(margin, Y), (margin + w * scale, Y)], fill=(255, 255, 255) if y % step == 0 else (60, 60, 70))
    for x in range(x0, x1 + 1):
        if x % step == 0:
            draw.text((margin + (x - x0) * scale + 2, 6), str(x), fill=(230, 230, 120), font=font)
    for y in range(y0, y1 + 1):
        if y % step == 0:
            draw.text((2, margin + (y - y0) * scale + 2), str(y), fill=(230, 230, 120), font=font)
    if panels:
        ox = margin + w * scale + 6
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                draw.point((ox + (x - x0), margin + (y - y0)), fill=colour_at(x, y) or (70, 70, 78))
    out.save(path)
    return str(Path(path).resolve())


def dump_text(canvas: PaintCanvas, region=None) -> str:
    """Compact ASCII rows (0-9a-z = palette index, . = transparent), reusable with the `rows` op."""
    x0, y0, x1, y1 = region or content_bbox(canvas) or (0, 0, canvas.width - 1, canvas.height - 1)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(canvas.width - 1, x1), min(canvas.height - 1, y1)
    sym = lambda v: "." if v == -1 else (str(v) if v < 10 else chr(ord("a") + v - 10))
    used = sorted({canvas.pixels[y][x] for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)} - {-1})
    lines = [f"x0={x0} y0={y0} (rows: y, columns from x0)"]
    lines += [f"{y:2d} " + "".join(sym(canvas.pixels[y][x]) for x in range(x0, x1 + 1)) for y in range(y0, y1 + 1)]
    lines.append("colors: " + " ".join(f"{sym(i)}={canvas.palette[i]}" for i in used))
    return "\n".join(lines)


# ───────────────────────── Reference tools ─────────────────────────

def refmap(path, size=None, colors=10, palette=None, region=None) -> str:
    """Reference image -> compact ASCII colour map on the target grid, instead of looking at the image repeatedly."""
    im = Image.open(path).convert("RGBA")
    im = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im).convert("RGB")
    if size:
        im = im.resize(size, Image.BOX)
    pal = palette or C.palette_from_image(path, colors)
    pal_rgb = [C.to_rgb(h) for h in pal]
    W, H = im.size
    sym = lambda v: str(v) if v < 10 else chr(ord("a") + v - 10)
    rows, counts = [], [0] * len(pal)
    for y in range(H):
        row = ""
        for x in range(W):
            r, g, b = im.getpixel((x, y))
            i = min(range(len(pal_rgb)), key=lambda k: 2 * (r - pal_rgb[k][0]) ** 2 + 4 * (g - pal_rgb[k][1]) ** 2
                    + 3 * (b - pal_rgb[k][2]) ** 2)
            counts[i] += 1
            row += sym(i)
        rows.append(row)
    x0, y0, x1, y1 = region or (0, 0, W - 1, H - 1)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W - 1, x1), min(H - 1, y1)
    lines = [f"x0={x0} y0={y0}  grid {W}x{H}"] + [f"{y:2d} " + rows[y][x0:x1 + 1] for y in range(y0, y1 + 1)]
    total = W * H
    lines.append("colors: " + " ".join(f"{sym(i)}={pal[i]}({100 * counts[i] // total}%)" for i in range(len(pal)) if counts[i]))
    return "\n".join(lines)


def compare(canvas: PaintCanvas, image: str, ref_size=None, at=(0, 0), out: str | None = None) -> str:
    """Compare a design with a reference image numerically (similarity %, worst deviations) and write a
    [reference | design | deviation] picture. `at` = where the design's (0,0) lies in the reference grid."""
    ref = Image.open(image).convert("RGBA")
    ref = Image.alpha_composite(Image.new("RGBA", ref.size, (255, 255, 255, 255)), ref).convert("RGB")
    if ref_size and ref.size != tuple(ref_size):
        ref = ref.resize(tuple(ref_size), Image.BOX)
    bbox = content_bbox(canvas)
    if not bbox:
        return "Design is empty."
    ox, oy = at
    diffs, total = [], 0.0
    for y in range(bbox[1], bbox[3] + 1):
        for x in range(bbox[0], bbox[2] + 1):
            v = canvas.pixels[y][x]
            rx, ry = x + ox, y + oy
            if v == -1 or not (0 <= rx < ref.width and 0 <= ry < ref.height):
                continue
            mine, theirs = C.to_rgb(canvas.palette[v]), ref.getpixel((rx, ry))
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(mine, theirs)))
            total += distance
            diffs.append((distance, x, y, mine, theirs))
    if not diffs:
        return "No overlap - check --at / --ref-size."
    mean = total / len(diffs)
    hexs = lambda t: "#%02x%02x%02x" % t
    lines = [f"similarity {100 * (1 - mean / 441.7):.1f}%  (mean colour distance {mean:.0f}/442 over {len(diffs)} px)",
             "worst deviations (x,y: design vs reference): " +
             " ".join(f"({x},{y}):{hexs(s)}/{hexs(r)}" for _, x, y, s, r in sorted(diffs, reverse=True)[:8])]
    x0, y0, x1, y1 = max(0, bbox[0] - 1), max(0, bbox[1] - 1), min(canvas.width - 1, bbox[2] + 1), min(canvas.height - 1, bbox[3] + 1)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    s = max(3, min(10, 300 // max(w, h)))
    img = Image.new("RGB", (3 * w * s + 16, h * s), (28, 28, 34))
    draw = ImageDraw.Draw(img)
    heat = {(x, y): d for d, x, y, _, _ in diffs}
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            rx, ry = x + ox, y + oy
            ref_px = ref.getpixel((rx, ry)) if 0 <= rx < ref.width and 0 <= ry < ref.height else (60, 60, 60)
            v = canvas.pixels[y][x]
            mine = C.to_rgb(canvas.palette[v]) if v != -1 else ((200, 200, 200) if (x + y) % 2 == 0 else (150, 150, 150))
            heat_px = (min(255, int(heat.get((x, y), 0) / 441.7 * 600)), 0, 0) if (x, y) in heat else (40, 40, 48)
            for i, colour in enumerate((ref_px, mine, heat_px)):
                X, Y = i * (w * s + 8) + (x - x0) * s, (y - y0) * s
                draw.rectangle([X, Y, X + s - 1, Y + s - 1], fill=colour)
    path = Path(out) if out else store.WORK / f"compare_{canvas.gid}.png"
    img.save(path)
    lines.append(f"image [reference | design | deviation]: {path.resolve()}  (x{x0}-{x1} y{y0}-{y1})")
    return "\n".join(lines)


# ───────────────────────── Export ─────────────────────────

def export(canvas: PaintCanvas, size: tuple[int, int] | None = None, at=(0, 0), scale: int = 1,
           out: str | None = None, data_uri: bool = False) -> str:
    """Write a PNG. Default: the usable rectangle (or the content bounds for square designs).
    size=(w,h) places the design on a transparent canvas of that size at `at`."""
    img = canvas.to_image()
    if size:
        base = Image.new("RGBA", tuple(size), (0, 0, 0, 0))
        base.paste(img, tuple(at))
        img = base
    elif not canvas.is_rect:
        bbox = content_bbox(canvas)
        if bbox:
            img = img.crop((bbox[0], bbox[1], bbox[2] + 1, bbox[3] + 1))
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    path = Path(out) if out else store.OUTPUT / f"export_{canvas.gid}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    message = f"exported: {path.resolve()}  ({img.width}x{img.height})"
    if data_uri:
        buf = io.BytesIO()
        img.save(buf, "PNG")
        uri = Path(str(path) + ".datauri.txt")
        uri.write_text("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
        message += f"\ndata URI: {uri.resolve()}"
    return message


def design_image(gid: int) -> Image.Image:
    """The design as RGBA, cropped to its rectangle."""
    return store.load(gid).to_image()


# ───────────────────────── Compose, mock-ups, sheets ─────────────────────────

_LAYER = re.compile(r"^(?P<src>[^@*:]+)(?:@(?P<x>-?\d+),(?P<y>-?\d+))?(?:\*(?P<a>[\d.]+))?(?P<sh>:sh)?$")


def load_source(src: str) -> Image.Image:
    """'g12' / '12' = a design, otherwise a PNG path."""
    if re.fullmatch(r"g?\d+", src):
        return design_image(int(src.lstrip("g")))
    return Image.open(src).convert("RGBA")


def _paste(base: Image.Image, img: Image.Image, x: int, y: int) -> None:
    base.paste(img, (x, y), img)           # unlike alpha_composite this tolerates negative offsets and overhang


def compose(layers: list[str], size: tuple[int, int], background: str | None = None) -> Image.Image:
    """Stack layers bottom -> top. Each layer: SOURCE[@x,y][*opacity][:sh]  (:sh = soft 1px drop shadow)."""
    W, H = size
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if background:
        base = Image.new("RGBA", (W, H), C.to_rgb(background) + (255,))
    for spec in layers:
        match = _LAYER.match(spec)
        if not match:
            raise ValueError(f"Layer '{spec}' not understood (form: gNN@x,y*opacity:sh)")
        img = load_source(match["src"])
        x, y = int(match["x"] or 0), int(match["y"] or 0)
        if match["a"]:
            opacity = float(match["a"])
            img = img.copy()
            img.putalpha(img.getchannel("A").point(lambda v: int(v * opacity)))
        if match["sh"]:
            shadow = Image.new("RGBA", img.size, (0, 0, 0, 255))
            shadow.putalpha(img.getchannel("A").point(lambda v: int(v * 0.35)))
            _paste(base, shadow, x + 1, y + 1)
        _paste(base, img, x, y)
    return base


def mockup(design: Image.Image, base: Image.Image, at: tuple[int, int] | None = None,
           fit: int | None = None) -> Image.Image:
    """Place a design onto a base image (a card, a UI panel, a tile). `fit` resizes the design to that many pixels
    (nearest neighbour). Default position: centred."""
    base = base.copy()
    if fit:
        factor = fit / max(design.size)
        design = design.resize((round(design.width * factor), round(design.height * factor)), Image.NEAREST)
    x, y = at if at else ((base.width - design.width) // 2, (base.height - design.height) // 2)
    _paste(base, design, x, y)
    return base


def zoom_sheet(image: Image.Image, scales=(1, 3, 8), small: float = 0.6) -> Image.Image:
    """The same picture at several zoom levels plus a reduced 'how it reads in the game HUD' version, side by side."""
    pieces = [image.resize((image.width * s, image.height * s), Image.NEAREST) for s in scales]
    pieces.append(image.resize((max(1, round(image.width * small * 3)), max(1, round(image.height * small * 3))), Image.BOX))
    width = sum(p.width for p in pieces) + 16 * (len(pieces) + 1)
    height = max(p.height for p in pieces) + 32
    sheet = checker(width, height, 8)
    x = 16
    for piece in pieces:
        _paste(sheet, piece, x, 16 + (height - 32 - piece.height) // 2)
        x += piece.width + 16
    return sheet


def checker(width: int, height: int, cell: int = 4) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            draw.rectangle([x, y, x + cell - 1, y + cell - 1],
                           fill=(60, 52, 46, 255) if (x // cell + y // cell) % 2 == 0 else (72, 63, 56, 255))
    return img


def contact_sheet(items: list[tuple[str, Image.Image, str]], columns: int = 4, cell: int = 240) -> Image.Image:
    """One overview picture for many designs: (name, image, note) per cell."""
    font = ImageFont.load_default()
    rows = (len(items) + columns - 1) // columns
    sheet = checker(columns * (cell + 12) + 12, rows * (cell + 30) + 12, 8)
    draw = ImageDraw.Draw(sheet)
    for i, (name, img, note) in enumerate(items):
        scale = max(1, min(10, cell // max(img.width, img.height)))
        shown = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
        left, top = 12 + (i % columns) * (cell + 12), 12 + (i // columns) * (cell + 30)
        _paste(sheet, shown, left + (cell - shown.width) // 2, top + (cell - shown.height) // 2)
        draw.text((left, top + cell + 4), name[:34], fill=(255, 230, 140), font=font)
        draw.text((left, top + cell + 15), note[:46], fill=(190, 190, 190), font=font)
    return sheet


# ───────────────────────── Reference image -> pixels ─────────────────────────

def image_to_pixels(path: str, size: int, palette: list[str] | None = None, colors: int = 12,
                    smooth: bool = True, alpha_cut: int = 128):
    """Reference image -> size x size palette pixels (aspect ratio kept, centred, transparent where alpha is low).
    Returns (pixels, palette)."""
    im = Image.open(path).convert("RGBA")
    bbox = im.getchannel("A").point(lambda a: 255 if a >= alpha_cut else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    factor = size / max(w, h)
    nw, nh = max(1, round(w * factor)), max(1, round(h * factor))
    im = im.resize((nw, nh), Image.LANCZOS if smooth else Image.NEAREST)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - nw) // 2, (size - nh) // 2))
    palette = palette or C.palette_from_image(path, colors)
    palette_rgb = [C.to_rgb(h) for h in palette]
    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            r, g, b, a = canvas.getpixel((x, y))
            if a < alpha_cut:
                row.append(-1)
                continue
            # weighted RGB distance (the eye is most sensitive to green)
            row.append(min(range(len(palette_rgb)), key=lambda i: 2 * (r - palette_rgb[i][0]) ** 2
                           + 4 * (g - palette_rgb[i][1]) ** 2 + 3 * (b - palette_rgb[i][2]) ** 2))
        pixels.append(row)
    return pixels, palette

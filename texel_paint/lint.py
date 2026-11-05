"""Quality check as text: judge a design without looking at a picture."""

from texel_paint import colors as C
from texel_paint.store import PaintCanvas

MAX_COLORS = 24            # warn above this many used colors
DARK_EDGE_PERCENT = 70     # sprites with transparency should have mostly dark edge pixels


def lint(canvas: PaintCanvas) -> tuple[str, list[str]]:
    """Returns (one-line summary, warnings). Dithering is not flagged as noise (diagonal neighbours count)."""
    w, h, P = canvas.width, canvas.height, canvas.pixels
    cells = [(x, y) for y in range(h) for x in range(w) if P[y][x] != -1]
    if not cells:
        return "empty", ["empty"]
    warnings = []
    used = {P[y][x] for (x, y) in cells}
    members, seen, components = set(cells), set(), []
    for start in cells:                                     # connected pieces (8-neighbourhood)
        if start in seen:
            continue
        stack, size = [start], 0
        seen.add(start)
        while stack:
            x, y = stack.pop()
            size += 1
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (x + dx, y + dy)
                    if nb in members and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        components.append(size)
    tiny = [s for s in components if s < 4]
    if tiny:
        warnings.append(f"{len(tiny)} stray pieces <4px")
    lone = [(x, y) for (x, y) in cells
            if not any(P[y + dy][x + dx] == P[y][x] for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy)
                       if 0 <= x + dx < w and 0 <= y + dy < h)]
    if len(lone) > max(8, len(cells) // 8):
        warnings.append(f"{len(lone)} single pixels (e.g. {lone[:3]})")
    edge = [(x, y) for (x, y) in cells
            if any(not (0 <= x + dx < w and 0 <= y + dy < h) or P[y + dy][x + dx] == -1
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    dark = sum(1 for (x, y) in edge if C.luminance(canvas.palette[P[y][x]]) < 95)
    outline = 100 * dark // max(1, len(edge))
    if edge and len(cells) < w * h * 0.97 and outline < DARK_EDGE_PERCENT:
        warnings.append(f"outline only {outline}% dark")
    if len(used) > MAX_COLORS:
        warnings.append(f"{len(used)} colors (>{MAX_COLORS})")
    mismatch = sum(1 for (x, y) in cells if P[y][w - 1 - x] != P[y][x])
    summary = (f"{w}x{h} coverage {100 * len(cells) // (w * h)}% colors {len(used)} pieces {len(components)} "
               f"single-px {len(lone)} outline {outline}% symmetry {100 - 100 * mismatch // len(cells)}%")
    return summary, warnings

"""
The Painter: every drawing operation, plus region selection and the op runner.

Conventions
-----------
* (0,0) is the top-left pixel, x grows right, y grows down.
* Colors are palette indices or hex strings (#rgb, #rrggbb, #rrggbbaa). An unknown hex color is appended to the
  palette automatically (and reported), so you never have to look up indices.
* The classic ops (circle, ellipse, ring ...) take pixel indices as centres.
  The newer shape ops (disc, donut, heart, leaf, star ...) take *pixel-edge* coordinates: 36 is the edge between
  pixels 35 and 36, 35.5 is the middle of pixel 35. Even-width shapes are therefore perfectly symmetric.
* A *region* is a list: [rect,x1,y1,x2,y2] [ellipse,cx,cy,rx,ry] [circle,cx,cy,r] [poly,[[x,y],..]] [all] [filled]
  [color,c1,c2] [union,r1,r2] [minus,r1,r2] [inter,r1,r2], and every new shape: [disc,..] [donut,..] [rrect,..]
  [heart,..] [leaf,..] [star,..] [diamond,..] [arc,..].
"""

import math

from texel_paint import colors as C
from texel_paint.effects import EffectsMixin
from texel_paint.parts import PartsMixin
from texel_paint.shapes import ShapesMixin, shape_mask
from texel_paint.stamps import StampsMixin
from texel_paint.store import PaintCanvas

MAX_COLORS = 255
MAX_COORDINATE = 100000
# Ops whose arguments must be whole pixels: floats coming from ${...} expressions are rounded for them.
INTEGER_OPS = {"px", "rect", "line", "tri", "fill", "circle", "ellipse", "replace", "shift", "mirror", "ring", "ellring"}


class Painter(ShapesMixin, EffectsMixin, StampsMixin, PartsMixin):
    """Applies drawing operations to a PaintCanvas. Public methods without a leading underscore are ops."""

    def __init__(self, canvas: PaintCanvas):
        self.c = canvas
        self.n = canvas.size
        self.w = canvas.width
        self.h = canvas.height
        self.notes: list[str] = []

    # ───────────── helpers ─────────────

    def _in(self, x, y) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def _hx(self, value):
        """Hex color -> palette index (appends unknown colors). Integers pass through."""
        if isinstance(value, int):
            return value
        h = C.norm_hex(value)
        palette = self.c.palette
        lowered = [p.lower() for p in palette]
        if h in lowered:
            return lowered.index(h)
        if len(palette) < MAX_COLORS:
            palette.append(h)
            self.notes.append(f"{h}={len(palette) - 1}")
            return len(palette) - 1
        r, g, b = C.to_rgb(h)
        best = min(range(len(palette)), key=lambda i: sum((a - c) ** 2 for a, c in zip(C.to_rgb(palette[i]), (r, g, b))))
        self.notes.append(f"PALETTE FULL: {h} -> {palette[best]}")
        return best

    def _hexof(self, value) -> str:
        """Color as '#rrggbb' text (palette indices are looked up)."""
        return C.norm_hex(self.c.palette[value])[:7] if isinstance(value, int) else C.norm_hex(value)[:7]

    def _col(self, col) -> int:
        if not (-1 <= col < len(self.c.palette)):
            raise ValueError(f"color index {col} invalid (-1..{len(self.c.palette) - 1})")
        return col

    def _resolve(self, obj):
        """Replace '#hex' strings (also inside lists and dict keys/values) by palette indices."""
        if isinstance(obj, str) and obj.startswith("#"):
            return self._hx(obj)
        if isinstance(obj, list):
            return [self._resolve(v) for v in obj]
        if isinstance(obj, dict):
            return {(self._hx(k) if str(k).startswith("#") else k): self._resolve(v) for k, v in obj.items()}
        return obj

    # ───────────── basic ops ─────────────

    def px(self, x, y, col):
        """px x y c  One pixel."""
        if self._in(x, y):
            self.c.pixels[y][x] = self._col(col)

    def pxs(self, items):
        """pxs [[x,y,c],..]  Many pixels at once."""
        for x, y, col in items:
            self.px(x, y, col)

    def rect(self, x1, y1, x2, y2, col):
        """rect x1 y1 x2 y2 c  Filled rectangle (inclusive)."""
        self.c.fill_rect(x1, y1, x2, y2, self._col(col))

    def line(self, x1, y1, x2, y2, col):
        """line x1 y1 x2 y2 c  Bresenham line."""
        self.c.draw_line(x1, y1, x2, y2, self._col(col))

    def circle(self, cx, cy, r, col, fill=True):
        """circle cx cy r c [fill=t]  Circle centred on pixel (cx,cy); fills by default (outline: ring)."""
        self.c.draw_circle(cx, cy, r, self._col(col), fill)

    def ellipse(self, cx, cy, rx, ry, col, fill=True):
        """ellipse cx cy rx ry c [fill=t]  Ellipse; FILLS by default (outline only: ellring)."""
        self.c.draw_ellipse(cx, cy, rx, ry, self._col(col), fill)

    def tri(self, x1, y1, x2, y2, x3, y3, col):
        """tri x1 y1 x2 y2 x3 y3 c  Filled triangle."""
        self.c.draw_triangle(x1, y1, x2, y2, x3, y3, self._col(col), True)

    def poly(self, points, col):
        """poly [[x,y],..] c  Filled polygon (float points use pixel centres at x+0.5)."""
        self.fillr(["poly", points], col)

    def bezier(self, p0, p1, p2, r0, r1, col, steps=160):
        """bezier [x,y] [x,y] [x,y] r0 r1 c  Quadratic curve with radius tapering from r0 to r1 (stems, tails)."""
        col = self._col(col)
        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
            r = r0 + (r1 - r0) * t
            for yy in range(int(y - r - 1), int(y + r + 2)):
                for xx in range(int(x - r - 1), int(x + r + 2)):
                    if (xx - x) ** 2 + (yy - y) ** 2 <= r * r:
                        self.px(xx, yy, col)

    def fill(self, x, y, col):
        """fill x y c  Flood fill from a pixel."""
        if not self._in(x, y):
            return
        target, col = self.c.pixels[y][x], self._col(col)
        if target == col:
            return
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if self._in(cx, cy) and self.c.pixels[cy][cx] == target:
                self.c.pixels[cy][cx] = col
                stack += [(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)]

    def replace(self, a, b):
        """replace a b  Change every pixel of color a into color b."""
        b = self._col(b)
        for row in self.c.pixels:
            for x in range(self.n):
                if row[x] == a:
                    row[x] = b

    def mirror(self, axis="x"):
        """mirror x|y  Mirror the left (x) or top (y) half of the whole canvas onto the other half."""
        n, P = self.n, self.c.pixels
        for y in range(n):
            for x in range(n // 2):
                if axis == "x":
                    P[y][n - 1 - x] = P[y][x]
        if axis == "y":
            for y in range(n // 2):
                P[n - 1 - y] = P[y][:]

    def outline(self, col, inner=False):
        """outline c [inner]  1px outline around the shape. Apply ONCE (twice = double outline). See autoline for nicer colors."""
        col, n = self._col(col), self.n
        src = [r[:] for r in self.c.pixels]
        for y in range(n):
            for x in range(n):
                nb = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
                if not inner and src[y][x] == -1 and any(self._in(a, b) and src[b][a] != -1 for a, b in nb):
                    self.c.pixels[y][x] = col
                elif inner and src[y][x] != -1 and any((not self._in(a, b)) or src[b][a] == -1 for a, b in nb):
                    self.c.pixels[y][x] = col

    def shade_disc(self, cx, cy, r, ramp, light=(-0.6, -0.8)):
        """shade_disc cx cy r [c_dark,..,c_light]  Lit sphere (light from top-left) using a colour ramp."""
        k = len(ramp)
        for y in range(self.n):
            for x in range(self.n):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r + r * 0.6:
                    t = (((x - cx) * light[0] + (y - cy) * light[1]) / max(r, 1) + 0.9) / 1.8
                    self.c.pixels[y][x] = self._col(ramp[min(k - 1, max(0, int(t * k)))])

    def noise(self, x1, y1, x2, y2, colors, seed=42):
        """noise x1 y1 x2 y2 [c1,c2,..] [seed]  Random colour distribution in a rectangle (natural texture)."""
        self.c.fill_noise(x1, y1, x2, y2, colors, seed)

    def voronoi(self, x1, y1, x2, y2, colors, cells=8, seed=42):
        """voronoi x1 y1 x2 y2 [colors] [cells] [seed]  Cell pattern (cobblestone, rocks, scales)."""
        self.c.fill_voronoi(x1, y1, x2, y2, colors, cells, seed)

    def dither(self, x1, y1, x2, y2, a, b):
        """dither x1 y1 x2 y2 a b  Checkerboard of two colours."""
        for y in range(max(0, y1), min(self.n, y2 + 1)):
            for x in range(max(0, x1), min(self.n, x2 + 1)):
                self.c.pixels[y][x] = self._col(a if (x + y) % 2 == 0 else b)

    def rows(self, x0, y0, lines, legend=None):
        """rows x0 y0 ["ascii",..]  ASCII pixel rows: 0-9a-z = palette index, . = transparent, _ = unchanged."""
        for dy, line in enumerate(lines):
            for dx, ch in enumerate(line):
                if ch == "_":
                    continue
                value = -1 if ch == "." else (legend[ch] if legend and ch in legend else int(ch, 36))
                self.px(x0 + dx, y0 + dy, value)

    # ───────────── regions ─────────────

    def _mask(self, spec) -> set:
        w, h, P = self.w, self.h, self.c.pixels
        kind = spec[0]
        if kind == "all":
            return {(x, y) for y in range(h) for x in range(w)}
        if kind == "filled":
            return {(x, y) for y in range(h) for x in range(w) if P[y][x] != -1}
        if kind == "rect":
            x1, y1, x2, y2 = spec[1:5]
            return {(x, y) for y in range(max(0, int(y1)), min(h, int(y2) + 1))
                    for x in range(max(0, int(x1)), min(w, int(x2) + 1))}
        if kind in ("ellipse", "circle"):
            cx, cy = spec[1], spec[2]
            rx, ry = (spec[3], spec[4]) if kind == "ellipse" else (spec[3], spec[3])
            rx, ry = max(rx, 0.5), max(ry, 0.5)
            return {(x, y) for y in range(h) for x in range(w) if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1}
        if kind == "poly":
            return self._poly_mask(spec[1])
        if kind == "color":
            wanted = spec[1] if isinstance(spec[1], list) else list(spec[1:])
            return {(x, y) for y in range(h) for x in range(w) if P[y][x] in wanted}
        if kind == "union":
            cells = set()
            for sub in spec[1:]:
                cells |= self._mask(sub)
            return cells
        if kind == "minus":
            return self._mask(spec[1]) - self._mask(spec[2])
        if kind == "inter":
            return self._mask(spec[1]) & self._mask(spec[2])
        return shape_mask(spec, self.n)

    def _poly_mask(self, points) -> set:
        cells = set()
        for y in range(self.h):
            for x in range(self.w):
                px, py, inside, j = x + 0.5, y + 0.5, False, len(points) - 1
                for i in range(len(points)):
                    xi, yi = points[i]
                    xj, yj = points[j]
                    if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                        inside = not inside
                    j = i
                if inside:
                    cells.add((x, y))
        return cells

    def fillr(self, region, col, only=None):
        """fillr region c [only]  Fill a region (only=[colors]: overwrite just pixels that currently have these colours)."""
        col = self._col(col)
        only = [only] if isinstance(only, int) else only
        P = self.c.pixels
        for x, y in self._mask(region):
            if only is None or P[y][x] in only:
                P[y][x] = col

    def recolor(self, region, src, dst):
        """recolor region src dst  Change colours src (index or list) into dst, only inside the region."""
        src = [src] if isinstance(src, int) else src
        dst, P = self._col(dst), self.c.pixels
        for x, y in self._mask(region):
            if P[y][x] in src:
                P[y][x] = dst

    def pattern(self, region, kind, a, b, size=4, only_filled=True):
        """pattern region checker|stripes_h|stripes_v|diag|diag2|argyle|dots a b [size]  Pattern on painted pixels."""
        a, b, P = self._col(a), self._col(b), self.c.pixels
        for x, y in self._mask(region):
            if only_filled and P[y][x] == -1:
                continue
            if kind == "dots":
                if x % size == 0 and y % size == 0:
                    P[y][x] = b
                continue
            parity = {"checker": x // size + y // size, "stripes_h": y // size, "stripes_v": x // size,
                      "diag": (x + y) // size, "diag2": (x - y + 4096) // size,
                      "argyle": (x + y) // size + (x - y + 4096) // size}[kind] & 1
            P[y][x] = b if parity else a

    def shade(self, region, ramp, lx=-0.6, ly=-0.8, depth=0):
        """shade region [c_dark,..,c_light] [lx ly depth]  Automatic dome shading of any region (light from top-left)."""
        cells = self._mask(region)
        if not cells or not ramp:
            return
        norm = math.hypot(lx, ly) or 1
        lx, ly = lx / norm, ly / norm
        neighbours = ((1, 0), (-1, 0), (0, 1), (0, -1))
        dist = {c: 1 for c in cells if any((c[0] + dx, c[1] + dy) not in cells for dx, dy in neighbours)}
        frontier = list(dist)
        while frontier:
            nxt = []
            for (x, y) in frontier:
                for dx, dy in neighbours:
                    nb = (x + dx, y + dy)
                    if nb in cells and nb not in dist:
                        dist[nb] = dist[(x, y)] + 1
                        nxt.append(nb)
            frontier = nxt
        top = depth or max(dist.values())
        height = lambda x, y: min(dist.get((x, y), 0), top) / top
        k = len(ramp)
        for (x, y) in cells:
            gx, gy = height(x + 1, y) - height(x - 1, y), height(x, y + 1) - height(x, y - 1)
            magnitude = math.hypot(gx, gy)
            t = 0.55 if magnitude < 1e-6 else 0.5 + 0.5 * ((-gx * lx - gy * ly) / magnitude) * min(1.0, magnitude * top / 1.5)
            self.c.pixels[y][x] = self._col(ramp[min(k - 1, max(0, int(t * k)))])

    def soutline(self, default, mapping=None):
        """soutline c [{fill:outline,..}]  Selective outline per neighbouring colour. Apply ONCE."""
        default, n, src = self._col(default), self.n, [r[:] for r in self.c.pixels]
        table = {int(k): self._col(v) for k, v in (mapping or {}).items()}
        for y in range(n):
            for x in range(n):
                if src[y][x] != -1:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    a, b = x + dx, y + dy
                    if self._in(a, b) and src[b][a] != -1:
                        self.c.pixels[y][x] = table.get(src[b][a], default)
                        break

    def edge(self, a, b, col):
        """edge a b c  Separator line where colour a touches colour b (a pixels become c)."""
        col, n, src = self._col(col), self.n, [r[:] for r in self.c.pixels]
        for y in range(n):
            for x in range(n):
                if src[y][x] == a and any(self._in(x + dx, y + dy) and src[y + dy][x + dx] == b
                                          for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    self.c.pixels[y][x] = col

    def despeckle(self, mode="transparent", keep=None):
        """despeckle [transparent|majority] [keep]  Remove stray pixels."""
        n, src, keep = self.n, [r[:] for r in self.c.pixels], set(keep or [])
        around = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy]
        for y in range(n):
            for x in range(n):
                v = src[y][x]
                if v == -1 or v in keep:
                    continue
                nb = [src[y + dy][x + dx] for dx, dy in around if self._in(x + dx, y + dy)]
                if mode == "transparent":
                    if all(u == -1 for u in nb):
                        self.c.pixels[y][x] = -1
                elif not any(self._in(x + dx, y + dy) and src[y + dy][x + dx] == v
                             for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    candidates = [u for u in nb if u not in (-1, v)]
                    if candidates:
                        self.c.pixels[y][x] = max(set(candidates), key=candidates.count)

    def mirrorx(self, axis, side="l", clear=False):
        """mirrorx axis [l|r]  Mirror around a vertical axis (cell edge, e.g. 32 or 31.5). l = left to right."""
        P, src = self.c.pixels, [r[:] for r in self.c.pixels]
        for y in range(self.n):
            for x in range(self.n):
                if (side == "l") != (x + 0.5 < axis):
                    continue
                tx = int(round(2 * axis - 1 - x))
                if self._in(tx, y) and (clear or src[y][x] != -1):
                    P[y][tx] = src[y][x]

    def shift(self, dx, dy):
        """shift dx dy  Move all pixels."""
        n, src = self.n, [r[:] for r in self.c.pixels]
        self.c.pixels = [[src[y - dy][x - dx] if 0 <= x - dx < n and 0 <= y - dy < n else -1
                          for x in range(n)] for y in range(n)]

    def ring(self, cx, cy, ro, ri, col):
        """ring cx cy ro ri c  Hollow circle centred on pixel (cx,cy). For half-pixel centres use donut."""
        col = self._col(col)
        for y in range(self.n):
            for x in range(self.n):
                if ri * ri < (x - cx) ** 2 + (y - cy) ** 2 <= ro * ro:
                    self.c.pixels[y][x] = col

    def ellring(self, cx, cy, rx, ry, col, t=1):
        """ellring cx cy rx ry c [thickness]  Ellipse outline."""
        col = self._col(col)
        for y in range(self.n):
            for x in range(self.n):
                outer = ((x - cx) / max(rx, .5)) ** 2 + ((y - cy) / max(ry, .5)) ** 2
                inner = ((x - cx) / max(rx - t, .3)) ** 2 + ((y - cy) / max(ry - t, .3)) ** 2
                if outer <= 1 < inner:
                    self.c.pixels[y][x] = col


# ───────────────────────── Running ops ─────────────────────────

def apply_ops(canvas: PaintCanvas, ops: list) -> tuple[list[str], list[str]]:
    """Run a parsed op list on the canvas. Returns (errors, notes); a failing op does not stop the rest.
    Notes list colours that were added to the palette."""
    painter = Painter(canvas)
    errors = []
    for index, op in enumerate(ops):
        name = op[0]
        fn = getattr(painter, name, None)
        if fn is None or name.startswith("_") or not callable(fn):
            errors.append(f"op {index}: unknown op '{name}' (python -m texel_paint help-ops)")
            continue
        args = painter._resolve(op[1:])
        if name in INTEGER_OPS:
            args = [int(round(a)) if isinstance(a, float) else a for a in args]
        if any(isinstance(a, (int, float)) and not isinstance(a, bool) and abs(a) > MAX_COORDINATE for a in args):
            errors.append(f"op {index} {name}: absurd number in {args[:4]}")
            continue
        try:
            fn(*args)
        except Exception as exc:
            errors.append(f"op {index} {name}{tuple(args)[:3]}: {exc}")
    canvas.clip_to_rect()
    return errors, painter.notes


def op_reference() -> list[tuple[str, str]]:
    """(name, first docstring line) of every public op, grouped by definition order of the mixins."""
    seen, out = set(), []
    for cls in (Painter, ShapesMixin, EffectsMixin, StampsMixin, PartsMixin):
        for name, member in cls.__dict__.items():
            if name.startswith("_") or not callable(member) or name in seen or not member.__doc__:
                continue
            seen.add(name)
            out.append((name, member.__doc__.strip().splitlines()[0]))
    return out

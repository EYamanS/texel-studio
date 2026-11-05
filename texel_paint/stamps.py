"""
Stamp library: remember a piece of a design (colour-independent, stored as hex) and reuse it anywhere,
in any later run or design. Stored in paint_work/stamps/<name>.json.
"""

import json

from texel_paint import store

STAMPS = store.WORK / "stamps"


def list_stamps() -> list[str]:
    return sorted(p.stem for p in STAMPS.glob("*.json")) if STAMPS.exists() else []


def _rows(name: str, rotation: int, flip: str, scale: int) -> list[list]:
    path = STAMPS / f"{name}.json"
    if not path.exists():
        raise ValueError(f"Unknown stamp '{name}' (known: {', '.join(list_stamps()) or 'none'})")
    rows = json.loads(path.read_text())["rows"]
    if "x" in flip:
        rows = [r[::-1] for r in rows]
    if "y" in flip:
        rows = rows[::-1]
    for _ in range((int(rotation) // 90) % 4):
        rows = [list(r) for r in zip(*rows[::-1])]
    if scale > 1:
        rows = [[v for v in r for _ in range(scale)] for r in rows for _ in range(scale)]
    return rows


class StampsMixin:

    def grab(self, name, region):
        """grab name region  Remember the painted pixels of a region as a reusable stamp."""
        cells = self._mask(region)
        if not cells:
            raise ValueError("empty region")
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        rows = []
        for y in range(y0, y1 + 1):
            row = []
            for x in range(x0, x1 + 1):
                v = self.c.pixels[y][x]
                row.append(self.c.palette[v] if (x, y) in cells and 0 <= v < len(self.c.palette) else None)
            rows.append(row)
        STAMPS.mkdir(parents=True, exist_ok=True)
        (STAMPS / f"{name}.json").write_text(json.dumps({"w": x1 - x0 + 1, "h": y1 - y0 + 1, "rows": rows}))

    def stamp(self, name, x, y, rotation=0, flip="", scale=1, remap=None):
        """stamp name x y [rotation 0|90|180|270] [flip x|y|xy] [scale] [{#old:#new}]  Place a stamp (x,y = top-left)."""
        rows = _rows(name, rotation, flip, int(scale))
        table = {self._hexof(k).lower(): self._hexof(v) for k, v in (remap or {}).items()}
        for dy, row in enumerate(rows):
            for dx, colour in enumerate(row):
                if colour is not None:
                    self.px(x + dx, y + dy, self._hx(table.get(colour.lower()[:7], colour)))

    def stampc(self, name, cx, cy, rotation=0, flip="", scale=1, remap=None):
        """stampc name cx cy [rotation] [flip] [scale] [remap]  Place a stamp centred on (cx,cy)."""
        rows = _rows(name, rotation, flip, int(scale))
        self.stamp(name, int(round(cx - len(rows[0]) / 2)), int(round(cy - len(rows) / 2)), rotation, flip, scale, remap)

    def corners(self, name, x1, y1, x2, y2, inset=0):
        """corners name x1 y1 x2 y2 [inset]  Place a top-left corner stamp into all four corners of a rectangle."""
        rows = _rows(name, 0, "", 1)
        w, h = len(rows[0]), len(rows)
        self.stamp(name, x1 + inset, y1 + inset)
        self.stamp(name, x2 - inset - w + 1, y1 + inset, 0, "x")
        self.stamp(name, x1 + inset, y2 - inset - h + 1, 0, "y")
        self.stamp(name, x2 - inset - w + 1, y2 - inset - h + 1, 0, "xy")

"""
Ready-made parts: gem, rivet, sparkle, dew drop and a complete card frame (three rarity themes).
Colors for parts are derived from a single base color, so one line gives a coherent result.
"""

import math

from texel_paint import colors as C
from texel_paint.shapes import shape_mask

# o outline | gl/gm/gd frame light/mid/dark | br inner line | p/pl/ps paper base/light/shade | pd ring dark
# pf paper grain | dot corner dot | gh shine | gem gem colour
CARD_THEMES = {
    "common": dict(o="#2b1a0e", gl="#f6dc8a", gm="#e0b04a", gd="#a8772a", br="#7a4a1e", p="#f3e6c0", pl="#fbf3d8",
                   ps="#e4d5a6", pd="#cdb274", pf="#ebdcae", dot="#7a2a2a", gh="#fff6c8", gem="#2d3cff"),
    "rare": dict(o="#1a1620", gl="#d7e4f2", gm="#8fa8c4", gd="#4b6483", br="#33465e", p="#f1e8d6", pl="#faf4e6",
                 ps="#e0d4bc", pd="#a9b4c2", pf="#e6dcc6", dot="#2c4c7a", gh="#ffffff", gem="#e9e2d8"),
    "legendary": dict(o="#2b1608", gl="#fff5a6", gm="#ffd43a", gd="#d98e12", br="#9a4a10", p="#f7e9c6", pl="#fffaea",
                      ps="#ead8a8", pd="#e0b860", pf="#f1e0b4", dot="#d4531a", gh="#ffffff", gem="#ff8a1e"),
}


def _gem_ramp(base: str) -> list[str]:
    return [C.tone(base, -0.16, -8), base, C.tone(base, 0.14, 6), C.tone(base, 0.30, 10)]


class PartsMixin:

    def gem(self, cx, cy, size, base, bezel=None):
        """gem cx cy size #base [#bezel]  Faceted gem with lit top-left and a white shine; optional metal setting. Centre in pixel-edge coordinates."""
        r = size / 2.0
        base = self._hexof(base)
        bezel = self._hexof(bezel) if bezel is not None else None
        ramp, dark = _gem_ramp(base), C.tone(base, -0.36, -10, 1.1)
        if bezel:
            self.fillr(["disc", cx, cy, r + 2.0], self._hx(dark))
            self.fillr(["donut", cx, cy, r + 1.4, r + 0.3], self._hx(bezel))
            self.fillr(["arc", cx, cy, r + 0.85, 180, 270, 1.1], self._hx(C.tone(bezel, 0.12, 4)))
            self.fillr(["arc", cx, cy, r + 0.85, 0, 90, 1.1], self._hx(C.tone(bezel, -0.18, -6)))
        self.fillr(["disc", cx, cy, r], self._hx(dark))
        for (x, y) in shape_mask(["disc", cx, cy, r - 1.0], self.n):
            t = -((x + .5 - cx) + (y + .5 - cy)) / (r * 1.7)
            level = 3 if t > 0.38 else (2 if t > 0.0 else (1 if t > -0.35 else 0))
            self.c.pixels[y][x] = self._hx(ramp[level])
        hx, hy = int(math.floor(cx - r * 0.45)), int(math.floor(cy - r * 0.45))
        self.px(hx, hy, self._hx("#ffffff"))
        self.px(hx + 1, hy, self._hx(ramp[3]))
        self.px(hx, hy + 1, self._hx(ramp[3]))

    def rivet(self, cx, cy, base):
        """rivet cx cy #base  Small round stud with highlight."""
        base = self._hexof(base)
        ramp, outline = _gem_ramp(base), self._hx(C.tone(base, -0.36, -10, 1.1))
        for (x, y) in shape_mask(["disc", cx, cy, 2.1], self.n):
            self.c.pixels[y][x] = outline
        for (x, y) in shape_mask(["disc", cx, cy, 1.1], self.n):
            self.c.pixels[y][x] = self._hx(ramp[2])
        self.px(int(math.floor(cx - 0.6)), int(math.floor(cy - 0.6)), self._hx(ramp[3]))
        self.px(int(math.floor(cx + 0.1)), int(math.floor(cy + 0.1)), self._hx(ramp[1]))

    def sparkle(self, cx, cy, arm, col):
        """sparkle cx cy arm #color  Four-pointed glint with a white centre."""
        col = self._hx(self._hexof(col))
        x0, y0 = int(math.floor(cx)), int(math.floor(cy))
        for k in range(-arm, arm + 1):
            self.px(x0 + k, y0, col)
            self.px(x0, y0 + k, col)
        self.px(x0, y0, self._hx("#ffffff"))

    def dew(self, cx, cy, col):
        """dew cx cy #color  Tiny water drop with a white highlight."""
        col = self._hx(self._hexof(col))
        x, y = int(math.floor(cx)), int(math.floor(cy))
        for dx, dy in ((0, 0), (0, 1), (-1, 1), (1, 1), (0, 2)):
            self.px(x + dx, y + dy, col)
        self.px(x, y + 1, self._hx("#ffffff"))

    def card_frame(self, x1, y1, x2, y2, theme="common", medallion=1, stone=1, corners=1, grain=1, seed=7):
        """card_frame x1 y1 x2 y2 [common|rare|legendary|{theme}] [medallion=1] [stone=1] [corners=1] [grain=1] [seed=7]  Complete portrait card base (frame, paper, medallion, corner marks, gem). Tuned for 52x72."""
        colors = dict(CARD_THEMES["common"])
        if isinstance(theme, dict):
            colors.update({k: self._hexof(v) for k, v in theme.items()})
        else:
            colors.update(CARD_THEMES.get(str(theme), CARD_THEMES["common"]))
        col = lambda key: self._hx(colors[key])
        L, R, T, B = x1, x2, y1, y2
        cx, cy = (L + R + 1) / 2.0, T + 33.0
        P = self.c.pixels

        def fill(a, b, c, d, colour):
            for yy in range(max(0, b), min(self.n, d + 1)):
                for xx in range(max(0, a), min(self.n, c + 1)):
                    P[yy][xx] = colour

        # frame: outline, gold (light top-left, dark bottom-right), dark inner edge, paper
        fill(L, T, R, B, col("o"))
        fill(L + 1, T + 1, R - 1, B - 1, col("gm"))
        fill(L + 1, T + 1, R - 1, T + 1, col("gl"))
        fill(L + 1, T + 1, L + 1, B - 1, col("gl"))
        fill(L + 1, B - 1, R - 1, B - 1, col("gd"))
        fill(R - 1, T + 1, R - 1, B - 1, col("gd"))
        fill(L + 2, T + 2, R - 2, B - 2, col("gd"))
        fill(L + 3, T + 3, R - 3, B - 3, col("p"))
        fill(L + 3, T + 3, R - 3, T + 3, col("pl"))
        fill(L + 3, T + 3, L + 3, B - 3, col("pl"))
        fill(L + 3, B - 3, R - 3, B - 3, col("ps"))
        fill(R - 3, T + 3, R - 3, B - 3, col("ps"))
        for (x, y) in [(L, T), (L + 1, T), (L, T + 1), (R, T), (R - 1, T), (R, T + 1),
                       (L, B), (L + 1, B), (L, B - 1), (R, B), (R - 1, B), (R, B - 1)]:
            if 0 <= x < self.n and 0 <= y < self.n:
                P[y][x] = -1                                          # stepped corners
        for (x, y) in [(L + 1, T + 1), (R - 1, T + 1), (L + 1, B - 1), (R - 1, B - 1)]:
            P[y][x] = col("o")
        if grain:                                                      # paper fibres
            state = [seed or 1]

            def rnd():
                state[0] = (state[0] * 1103515245 + 12345) & 0x7fffffff
                return state[0] / 0x7fffffff
            for _ in range(70):
                x, y = int(L + 5 + rnd() * (R - L - 10)), int(T + 5 + rnd() * (B - T - 10))
                if medallion and (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 < 23 * 23:
                    continue
                colour = col("pf") if rnd() < 0.62 else col("pl")
                P[y][x] = colour
                if rnd() < 0.4 and x + 1 < R - 4:
                    P[y][x + 1] = colour
        if medallion:                                                  # round stage behind the artwork
            for (x, y) in shape_mask(["disc", cx, cy, 20.4], self.n):
                d = math.hypot(x + .5 - cx, y + .5 - cy)
                if d <= 15.2:
                    P[y][x] = col("pl")
                elif d <= 17.6:
                    P[y][x] = col("pl") if (x + y) % 2 == 0 else col("p")
                elif d <= 18.4:
                    P[y][x] = col("pd")
                elif d <= 19.6:
                    P[y][x] = col("gl") if (x + .5 - cx) + (y + .5 - cy) < 0 else col("gm")
                else:
                    P[y][x] = col("br")
            for ax, ay in ((0, -19.5), (19.5, 0), (0, 19.5), (-19.5, 0)):
                bx, by = int(cx + ax - (1 if ax <= 0 else 0)), int(cy + ay - (1 if ay <= 0 else 0))
                for ddx in range(-1, 3):
                    for ddy in range(-1, 3):
                        edge_x, edge_y = ddx in (-1, 2), ddy in (-1, 2)
                        if not (edge_x and edge_y):
                            P[by + ddy][bx + ddx] = col("o") if (edge_x or edge_y) else col("gm")
                P[by][bx] = col("gh")
                P[by + 1][bx + 1] = col("gd")
        if corners:                                                    # gold angle with a coloured dot
            tile = ["3333", "34..", "3.a.", "3..."]
            palette = {"3": col("gm"), "4": col("gl"), "a": col("dot")}
            for i, row in enumerate(tile):
                for j, ch in enumerate(row):
                    if ch != ".":
                        for (px, py) in ((L + 5 + j, T + 5 + i), (R - 5 - j, T + 5 + i),
                                         (L + 5 + j, B - 5 - i), (R - 5 - j, B - 5 - i)):
                            P[py][px] = palette[ch]
        if stone:                                                      # gem with scroll wings
            gy = T + 61.0
            for i in range(9):
                for xx in (int(cx) - 7 - i, int(cx) + 7 + i):
                    P[int(gy)][xx] = col("gm") if i < 7 else col("gd")
                    if i % 2 == 0:
                        P[int(gy) + 1][xx] = col("gd")
            self.gem(cx, gy, 6.2, colors["gem"], bezel=colors["gm"])

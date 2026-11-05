"""Light, color and cleanup ops that derive their colors from what is already painted (less guesswork, better results)."""

import math

from texel_paint import colors as C

BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def _bayer(x: int, y: int) -> float:
    return (BAYER4[y % 4][x % 4] + 0.5) / 16


class EffectsMixin:

    def bevel(self, region, light, shadow, width=1, highlight=None, deep=None):
        """bevel region light shadow [width=1] [highlight] [deep]  Light rim top-left, shadow rim bottom-right of any shape."""
        cells = self._mask(region)
        light, shadow = self._col(light), self._col(shadow)
        highlight = self._col(highlight) if highlight is not None else light
        deep = self._col(deep) if deep is not None else shadow
        out = {}
        for (x, y) in cells:
            up = any((x, y - k) not in cells for k in range(1, width + 1))
            left = any((x - k, y) not in cells for k in range(1, width + 1))
            down = any((x, y + k) not in cells for k in range(1, width + 1))
            right = any((x + k, y) not in cells for k in range(1, width + 1))
            if down or right:
                out[(x, y)] = deep if (down and right) else shadow
            elif up or left:
                out[(x, y)] = highlight if (up and left) else light
        for (x, y), col in out.items():
            self.c.pixels[y][x] = col

    def rim(self, region, amount=0.16, shade=0.2, width=1):
        """rim region [light=0.16] [shade=0.2] [width=1]  Like bevel, but uses each pixel's OWN colour (warmer lights, cooler shadows)."""
        cells, P, cache = self._mask(region), self.c.pixels, {}

        def tinted(idx, d_light, hue):
            key = (idx, d_light, hue)
            if key not in cache:
                cache[key] = self._hx(C.tone(self.c.palette[idx], d_light, hue))
            return cache[key]
        out = {}
        for (x, y) in cells:
            v = P[y][x]
            if v == -1:
                continue
            up = any((x, y - k) not in cells for k in range(1, width + 1))
            left = any((x - k, y) not in cells for k in range(1, width + 1))
            down = any((x, y + k) not in cells for k in range(1, width + 1))
            right = any((x + k, y) not in cells for k in range(1, width + 1))
            if down or right:
                out[(x, y)] = tinted(v, -shade, -8)
            elif up or left:
                out[(x, y)] = tinted(v, amount, 6)
        for (x, y), col in out.items():
            P[y][x] = col

    def autoline(self, darkness=0.42, hue=-10, diagonal=0):
        """autoline [darkness=0.42] [hue=-10] [diagonal=0]  Outline in a darker, cooler version of the neighbouring colour instead of black. Apply ONCE."""
        P, src = self.c.pixels, [r[:] for r in self.c.pixels]
        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)] + ([(1, 1), (-1, -1), (1, -1), (-1, 1)] if diagonal else [])
        cache = {}
        for y in range(self.h):
            for x in range(self.w):
                if src[y][x] != -1:
                    continue
                around = [src[y + dy][x + dx] for dx, dy in dirs
                          if 0 <= x + dx < self.w and 0 <= y + dy < self.h and src[y + dy][x + dx] != -1]
                if not around:
                    continue
                base = min(around, key=lambda i: C.luminance(self.c.palette[i]))
                if base not in cache:
                    colour = self.c.palette[base]
                    cache[base] = self._hx(C.tone(colour, -C.lightness(colour) * (1 - darkness), hue, 1.1))
                P[y][x] = cache[base]

    def polish(self):
        """polish  Cleanup: fill 1px holes inside shapes and remove single stray pixels."""
        P, src = self.c.pixels, [r[:] for r in self.c.pixels]
        for y in range(1, self.h - 1):
            for x in range(1, self.w - 1):
                around = [src[y + dy][x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
                if src[y][x] == -1 and all(v != -1 for v in around):
                    P[y][x] = max(set(around), key=around.count)
                elif src[y][x] != -1 and all(v == -1 for v in around):
                    P[y][x] = -1

    def gradient(self, region, ramp, angle=90, dither=1):
        """gradient region [c1,c2,..] [angle=90] [dither=1]  Colour ramp across a region with Bayer dithering (0 = left to right, 90 = top to bottom)."""
        cells, ramp = list(self._mask(region)), [self._col(c) for c in ramp]
        if not cells or not ramp:
            return
        dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        projection = {c: (c[0] + .5) * dx + (c[1] + .5) * dy for c in cells}
        low, high = min(projection.values()), max(projection.values())
        span, k = (high - low) or 1.0, len(ramp)
        for (x, y), value in projection.items():
            v = (value - low) / span * (k - 1)
            i = min(k - 2, int(v)) if k > 1 else 0
            frac = v - i
            step = 1 if k > 1 and (frac > _bayer(x, y) if dither else frac >= 0.5) else 0
            self.c.pixels[y][x] = ramp[min(k - 1, max(0, i + step))]

    def rgradient(self, region, ramp, cx=None, cy=None, r=None, dither=1):
        """rgradient region [c1,c2,..] [cx cy r] [dither=1]  Radial ramp: first colour in the centre, last at radius r."""
        cells, ramp = list(self._mask(region)), [self._col(c) for c in ramp]
        if not cells or not ramp:
            return
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        cx = cx if cx is not None else (min(xs) + max(xs) + 1) / 2
        cy = cy if cy is not None else (min(ys) + max(ys) + 1) / 2
        r = r or max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 1
        k = len(ramp)
        for (x, y) in cells:
            v = min(1.0, math.hypot(x + .5 - cx, y + .5 - cy) / r) * (k - 1)
            i = min(k - 2, int(v)) if k > 1 else 0
            frac = v - i
            step = 1 if k > 1 and (frac > _bayer(x, y) if dither else frac >= 0.5) else 0
            self.c.pixels[y][x] = ramp[min(k - 1, i + step)]

    def scatter(self, region, col, density, seed=7, pair=0.4):
        """scatter region c density [seed] [pair=0.4]  Scattered pixels (paper grain, dust); density 0..1, pair = share of double pixels."""
        col, state = self._col(col), [(seed * 2654435761) & 0x7fffffff or 1]

        def rnd():
            state[0] = (state[0] * 1103515245 + 12345) & 0x7fffffff
            return state[0] / 0x7fffffff
        cells = self._mask(region)
        for (x, y) in sorted(cells):
            if rnd() < density:
                self.c.pixels[y][x] = col
                if rnd() < pair and (x + 1, y) in cells:
                    self.c.pixels[y][x + 1] = col

    def shadow(self, dx, dy, col):
        """shadow dx dy c  Hard drop shadow: the painted area shifted by (dx,dy), drawn only onto empty pixels."""
        col, src = self._col(col), [r[:] for r in self.c.pixels]
        for y in range(self.n):
            for x in range(self.n):
                if src[y][x] != -1 and self._in(x + dx, y + dy) and src[y + dy][x + dx] == -1:
                    self.c.pixels[y + dy][x + dx] = col

    def pline(self, x1, y1, x2, y2, col):
        """pline x1 y1 x2 y2 c  Pixel-perfect line (no doubled L-corners)."""
        col = self._col(col)
        x1, y1, x2, y2 = (int(round(v)) for v in (x1, y1, x2, y2))
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        sx, sy = (1 if x1 < x2 else -1), (1 if y1 < y2 else -1)
        err, x, y, points = dx - dy, x1, y1, []
        for _ in range(dx + dy + 2):                      # hard upper bound: never an endless loop
            points.append((x, y))
            if (x, y) == (x2, y2):
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        i = 1
        while i < len(points) - 1:                        # drop the middle pixel of every L-shaped corner
            a, b, c = points[i - 1], points[i], points[i + 1]
            if a[0] != c[0] and a[1] != c[1] and (b[0] == a[0] or b[1] == a[1]) and (b[0] == c[0] or b[1] == c[1]):
                points.pop(i)
            else:
                i += 1
        for (px, py) in points:
            self.px(px, py, col)

    def mirrory(self, axis, side="t", clear=False):
        """mirrory axis [t|b]  Mirror around a horizontal axis (cell edge). t = top to bottom."""
        P, src = self.c.pixels, [r[:] for r in self.c.pixels]
        for y in range(self.n):
            if (side == "t") != (y + 0.5 < axis):
                continue
            ty = int(round(2 * axis - 1 - y))
            if 0 <= ty < self.n:
                for x in range(self.n):
                    if clear or src[y][x] != -1:
                        P[ty][x] = src[y][x]

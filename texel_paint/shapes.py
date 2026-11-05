"""
Parametric shapes, usable as ops (`heart 16 16 12 45 #43b85a`) and as regions (`fillr [heart,16,16,12,45] #43b85a`).

Centres are in pixel-edge coordinates: pixel (x,y) has its middle at (x+0.5, y+0.5). So 36.0 is the edge between
pixels 35 and 36 and a shape centred there is exactly symmetric for even widths.
"""

import math


def _cells(x0, y0, x1, y1, n, test) -> set:
    """All pixels in the bounding box whose middle passes `test(px, py)`."""
    out = set()
    for y in range(max(0, int(y0)), min(n, int(y1) + 1)):
        for x in range(max(0, int(x0)), min(n, int(x1) + 1)):
            if test(x + 0.5, y + 0.5):
                out.add((x, y))
    return out


def _in_polygon(px, py, points) -> bool:
    inside, j = False, len(points) - 1
    for i in range(len(points)):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _heart_test(length):
    """Returns inside(s, w): heart with its tip at s=0 pointing along +s (two round lobes + tapered body)."""
    lobe_s, lobe_w, lobe_r, tip = 0.69 * length, 0.24 * length, 0.28 * length, 0.095 * length

    def inside(s, w):
        for sign in (-1, 1):
            if math.hypot(s - lobe_s, w - sign * lobe_w) <= lobe_r:
                return True
        if tip <= s <= lobe_s:
            return abs(w) <= lobe_w * 0.98 * (s - tip) / (lobe_s - tip) + 0.35
        return False
    return inside


def shape_mask(spec, n) -> set:
    """Pixel set for a shape region spec such as ['disc', cx, cy, r]."""
    kind, a = spec[0], spec[1:]
    if kind == "disc":
        cx, cy, r = a[:3]
        return _cells(cx - r, cy - r, cx + r, cy + r, n, lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r)
    if kind == "donut":
        cx, cy, outer, inner = a[:4]
        return _cells(cx - outer, cy - outer, cx + outer, cy + outer, n,
                      lambda x, y: inner * inner < (x - cx) ** 2 + (y - cy) ** 2 <= outer * outer)
    if kind == "rrect":
        x1, y1, x2, y2, r = a[:5]
        right, bottom = x2 + 1, y2 + 1

        def test(x, y):
            ccx = x1 + r if x < x1 + r else (right - r if x > right - r else None)
            ccy = y1 + r if y < y1 + r else (bottom - r if y > bottom - r else None)
            return True if ccx is None or ccy is None else (x - ccx) ** 2 + (y - ccy) ** 2 <= r * r
        return _cells(x1, y1, x2, y2, n, test)
    if kind in ("heart", "leaf"):
        if kind == "heart":
            cx, cy, length, angle = a[:4]
            width, inside = length, _heart_test(length)
        else:
            cx, cy, length, width, angle = a[:5]
            inside = lambda s, w: 0 <= s <= length and abs(w) <= width / 2 * math.sin(math.pi * s / length)
        dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        reach = max(length, width) * 1.1
        return _cells(cx - reach, cy - reach, cx + reach, cy + reach, n,
                      lambda x, y: inside((x - cx) * dx + (y - cy) * dy, -(x - cx) * dy + (y - cy) * dx))
    if kind == "star":
        cx, cy, outer, inner, count, angle = a[:6]
        points = []
        for i in range(int(count) * 2):
            radius = outer if i % 2 == 0 else inner
            theta = math.radians(angle) + i * math.pi / count
            points.append((cx + radius * math.cos(theta), cy + radius * math.sin(theta)))
        return _cells(cx - outer, cy - outer, cx + outer, cy + outer, n, lambda x, y: _in_polygon(x, y, points))
    if kind == "diamond":
        cx, cy, rx, ry = a[:4]
        return _cells(cx - rx, cy - ry, cx + rx, cy + ry, n,
                      lambda x, y: abs(x - cx) / max(rx, 0.01) + abs(y - cy) / max(ry, 0.01) <= 1)
    if kind == "arc":
        cx, cy, r, start, end = a[:5]
        thickness = a[5] if len(a) > 5 else 1
        low, high = r - thickness / 2.0, r + thickness / 2.0

        def test(x, y):
            if not (low <= math.hypot(x - cx, y - cy) <= high):
                return False
            angle = math.degrees(math.atan2(y - cy, x - cx)) % 360
            s0, s1 = start % 360, end % 360
            return s0 <= angle <= s1 if s0 <= s1 else (angle >= s0 or angle <= s1)
        return _cells(cx - high, cy - high, cx + high, cy + high, n, test)
    raise ValueError(f"unknown region '{kind}'")


class ShapesMixin:
    """Shape ops. Each one is `fillr` with the matching region."""

    def disc(self, cx, cy, r, col):
        """disc cx cy r c  Filled circle, centre in pixel-edge coordinates (symmetric for even widths)."""
        self.fillr(["disc", cx, cy, r], col)

    def donut(self, cx, cy, outer, inner, col):
        """donut cx cy r_outer r_inner c  Ring, centre in pixel-edge coordinates."""
        self.fillr(["donut", cx, cy, outer, inner], col)

    def rrect(self, x1, y1, x2, y2, r, col):
        """rrect x1 y1 x2 y2 radius c  Rounded rectangle with stepped corners (x2,y2 inclusive)."""
        self.fillr(["rrect", x1, y1, x2, y2, r], col)

    def heart(self, cx, cy, length, angle, col):
        """heart tipx tipy length angle c  Heart with the tip at (tipx,tipy); angle in degrees (0 right, 90 down)."""
        self.fillr(["heart", cx, cy, length, angle], col)

    def leaf(self, cx, cy, length, width, angle, col):
        """leaf basex basey length width angle c  Lens/leaf shape starting at the base point."""
        self.fillr(["leaf", cx, cy, length, width, angle], col)

    def star(self, cx, cy, outer, inner, points, angle, col):
        """star cx cy r_outer r_inner points angle c  Star (angle -90 points up)."""
        self.fillr(["star", cx, cy, outer, inner, points, angle], col)

    def diamond(self, cx, cy, rx, ry, col):
        """diamond cx cy rx ry c  Rhombus."""
        self.fillr(["diamond", cx, cy, rx, ry], col)

    def arc(self, cx, cy, r, start, end, col, thickness=1):
        """arc cx cy r start end c [thickness]  Circle segment, angles in degrees clockwise from 3 o'clock."""
        self.fillr(["arc", cx, cy, r, start, end, thickness], col)

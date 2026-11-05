"""
Pure pixel canvas shared by the built-in AI agent (agent.py) and the agent-agnostic
painting CLI (texel_paint). It has no AI or network dependencies, only Pillow.

Pixels are palette indices; -1 is transparent.
"""

import base64
import io

from PIL import Image

class Canvas:
    def __init__(self, size: int, palette: list[str], pixels: list[list[int]] | None = None):
        self.size = size
        self.palette = palette
        self.pixels = pixels if pixels else [[-1] * size for _ in range(size)]

    def set_pixel(self, x: int, y: int, color: int) -> str:
        if not (0 <= x < self.size and 0 <= y < self.size):
            return f"Error: ({x},{y}) out of bounds (0-{self.size-1})"
        if color < -1 or color >= len(self.palette):
            return f"Error: color index {color} invalid (use -1 to {len(self.palette)-1})"
        self.pixels[y][x] = color
        return f"Set ({x},{y}) to {color}"

    def get_pixel(self, x: int, y: int) -> int:
        if 0 <= x < self.size and 0 <= y < self.size:
            return self.pixels[y][x]
        return -1

    def fill_rect(self, x1: int, y1: int, x2: int, y2: int, color: int) -> str:
        if color < -1 or color >= len(self.palette):
            return f"Error: color index {color} invalid"
        count = 0
        for y in range(max(0, y1), min(self.size, y2 + 1)):
            for x in range(max(0, x1), min(self.size, x2 + 1)):
                self.pixels[y][x] = color
                count += 1
        return f"Filled rect ({x1},{y1})-({x2},{y2}) with {color}, {count} pixels"

    def draw_line(self, x1: int, y1: int, x2: int, y2: int, color: int) -> str:
        if color < -1 or color >= len(self.palette):
            return f"Error: color index {color} invalid"
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy
        count = 0
        cx, cy = x1, y1
        while True:
            if 0 <= cx < self.size and 0 <= cy < self.size:
                self.pixels[cy][cx] = color
                count += 1
            if cx == x2 and cy == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                cx += sx
            if e2 < dx:
                err += dx
                cy += sy
        return f"Drew line, {count} pixels"

    def fill_row(self, y: int, x_start: int, x_end: int, color: int) -> str:
        if color < -1 or color >= len(self.palette):
            return f"Error: color index {color} invalid"
        count = 0
        for x in range(max(0, x_start), min(self.size, x_end + 1)):
            if 0 <= y < self.size:
                self.pixels[y][x] = color
                count += 1
        return f"Filled row y={y}, {count} pixels"

    def fill_column(self, x: int, y_start: int, y_end: int, color: int) -> str:
        if color < -1 or color >= len(self.palette):
            return f"Error: color index {color} invalid"
        count = 0
        for y in range(max(0, y_start), min(self.size, y_end + 1)):
            if 0 <= x < self.size:
                self.pixels[y][x] = color
                count += 1
        return f"Filled column x={x}, {count} pixels"

    def draw_rotated_rect(self, cx: int, cy: int, w: int, h: int, angle_deg: float, color: int) -> int:
        """Draw a filled rotated rectangle. cx,cy = center, w,h = full width/height, angle_deg = rotation."""
        import math
        rad = math.radians(angle_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        hw, hh = w / 2, h / 2
        # Check bounding box
        max_r = math.ceil(math.sqrt(hw * hw + hh * hh)) + 1
        count = 0
        for py in range(max(0, cy - max_r), min(self.size, cy + max_r + 1)):
            for px in range(max(0, cx - max_r), min(self.size, cx + max_r + 1)):
                # Rotate point into rect's local space
                dx = px - cx
                dy = py - cy
                lx = dx * cos_a + dy * sin_a
                ly = -dx * sin_a + dy * cos_a
                if abs(lx) <= hw and abs(ly) <= hh:
                    self.pixels[py][px] = color
                    count += 1
        return count

    def to_image(self) -> Image.Image:
        img = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        for y, row in enumerate(self.pixels):
            for x, idx in enumerate(row):
                if 0 <= idx < len(self.palette):
                    h = self.palette[idx]
                    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
                    img.putpixel((x, y), (r, g, b, 255))
        return img

    def to_grid_string(self) -> str:
        header = "    " + " ".join(f"{x:>3}" for x in range(self.size))
        rows = [f"{y:>3} " + " ".join(f"{v:>3}" for v in row) for y, row in enumerate(self.pixels)]
        return header + "\n" + "\n".join(rows)

    def to_visual_grid(self) -> str:
        """Compact visual grid using single-char symbols. Much easier for small LLMs to parse."""
        # Map palette indices to readable chars: 0=0, 1=1, ..., 9=9, 10=A, 11=B, ..., -1=.
        def _char(v: int) -> str:
            if v < 0: return "."
            if v < 10: return str(v)
            if v < 36: return chr(ord("A") + v - 10)
            return "#"

        # Column ruler
        if self.size <= 16:
            ruler = "   " + "".join(f"{x:X}" for x in range(self.size))
        else:
            # Two-line ruler for 32+
            tens = "   " + "".join(str(x // 10) if x >= 10 else " " for x in range(self.size))
            ones = "   " + "".join(f"{x % 10}" for x in range(self.size))
            ruler = tens + "\n" + ones

        rows = []
        for y, row in enumerate(self.pixels):
            label = f"{y:>2} " if self.size <= 16 else f"{y:>3}"
            rows.append(label + "".join(_char(v) for v in row))

        return ruler + "\n" + "\n".join(rows)

    def region_summary(self, y1: int, x1: int, y2: int, x2: int) -> str:
        """Describe what's in a rectangular region — helps the model understand spatial layout."""
        counts: dict[int, int] = {}
        for y in range(max(0, y1), min(self.size, y2 + 1)):
            for x in range(max(0, x1), min(self.size, x2 + 1)):
                v = self.pixels[y][x]
                counts[v] = counts.get(v, 0) + 1
        total = sum(counts.values())
        if total == 0:
            return "empty"
        parts = []
        for idx, c in sorted(counts.items(), key=lambda x: -x[1]):
            pct = c * 100 // total
            if pct < 5:
                continue
            if idx < 0:
                parts.append(f"empty:{pct}%")
            else:
                parts.append(f"{idx}:{pct}%")
        return " ".join(parts)

    # ── Shape drawing ──

    def draw_circle(self, cx: int, cy: int, radius: int, color: int, fill: bool = True) -> int:
        count = 0
        for y in range(max(0, cy - radius), min(self.size, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(self.size, cx + radius + 1)):
                dx, dy = x - cx, y - cy
                dist_sq = dx * dx + dy * dy
                r_sq = radius * radius
                if fill:
                    if dist_sq <= r_sq:
                        self.pixels[y][x] = color
                        count += 1
                else:
                    # Outline only — within 1px of the edge
                    if abs(dist_sq - r_sq) <= radius * 2:
                        self.pixels[y][x] = color
                        count += 1
        return count

    def draw_ellipse(self, cx: int, cy: int, rx: int, ry: int, color: int, fill: bool = True) -> int:
        count = 0
        for y in range(max(0, cy - ry), min(self.size, cy + ry + 1)):
            for x in range(max(0, cx - rx), min(self.size, cx + rx + 1)):
                dx, dy = (x - cx) / max(rx, 1), (y - cy) / max(ry, 1)
                dist = dx * dx + dy * dy
                if fill:
                    if dist <= 1.0:
                        self.pixels[y][x] = color
                        count += 1
                else:
                    if abs(dist - 1.0) <= 0.3:
                        self.pixels[y][x] = color
                        count += 1
        return count

    def draw_triangle(self, x1: int, y1: int, x2: int, y2: int, x3: int, y3: int, color: int, fill: bool = True) -> int:
        def sign(px, py, ax, ay, bx, by):
            return (px - bx) * (ay - by) - (ax - bx) * (py - by)

        min_x = max(0, min(x1, x2, x3))
        max_x = min(self.size - 1, max(x1, x2, x3))
        min_y = max(0, min(y1, y2, y3))
        max_y = min(self.size - 1, max(y1, y2, y3))

        count = 0
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                d1 = sign(x, y, x1, y1, x2, y2)
                d2 = sign(x, y, x2, y2, x3, y3)
                d3 = sign(x, y, x3, y3, x1, y1)
                has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
                has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
                if not (has_neg and has_pos):
                    self.pixels[y][x] = color
                    count += 1
        return count

    # ── Noise filling ──

    @staticmethod
    def _hash_noise(x: int, y: int, seed: int) -> float:
        n = x * 374761393 + y * 668265263 + seed * 1274126177
        n = ((n ^ (n >> 13)) * 1274126177) & 0x7fffffff
        n = n ^ (n >> 16)
        return (n & 0x7fffffff) / 0x7fffffff

    def fill_noise(self, x1: int, y1: int, x2: int, y2: int,
                   colors: list[int], seed: int = 42, scale: float = 1.0) -> int:
        """Simple value noise — distributes colors randomly based on noise."""
        count = 0
        n_colors = len(colors)
        if n_colors == 0:
            return 0
        for y in range(max(0, y1), min(self.size, y2 + 1)):
            for x in range(max(0, x1), min(self.size, x2 + 1)):
                n = self._hash_noise(int(x * scale), int(y * scale), seed)
                idx = int(n * n_colors) % n_colors
                self.pixels[y][x] = colors[idx]
                count += 1
        return count

    def fill_voronoi(self, x1: int, y1: int, x2: int, y2: int,
                     colors: list[int], num_points: int = 8, seed: int = 42) -> int:
        """Voronoi noise — creates cell-like patterns with given colors."""
        import math
        w = x2 - x1 + 1
        h = y2 - y1 + 1
        # Generate random seed points
        points = []
        for i in range(num_points):
            px = x1 + int(self._hash_noise(i, 0, seed) * w)
            py = y1 + int(self._hash_noise(0, i, seed + 99) * h)
            points.append((px, py, colors[i % len(colors)]))

        count = 0
        for y in range(max(0, y1), min(self.size, y2 + 1)):
            for x in range(max(0, x1), min(self.size, x2 + 1)):
                best_dist = float('inf')
                best_color = colors[0]
                for px, py, pc in points:
                    d = (x - px) ** 2 + (y - py) ** 2
                    if d < best_dist:
                        best_dist = d
                        best_color = pc
                self.pixels[y][x] = best_color
                count += 1
        return count

    def fill_noise_circle(self, cx: int, cy: int, radius: int,
                          colors: list[int], seed: int = 42) -> int:
        """Fill a circular area with noise-distributed colors."""
        count = 0
        n_colors = len(colors)
        if n_colors == 0:
            return 0
        for y in range(max(0, cy - radius), min(self.size, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(self.size, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                    n = self._hash_noise(x, y, seed)
                    self.pixels[y][x] = colors[int(n * n_colors) % n_colors]
                    count += 1
        return count

    def to_image_b64(self, scale: int = 512) -> str:
        img = self.to_image().resize((scale, scale), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

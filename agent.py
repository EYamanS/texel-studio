"""
Texel Studio Agent — LangGraph-based pixel art agent with canvas tools.

The agent gets a canvas, a palette, and tools to draw on it.
It thinks between each action, building up the sprite incrementally.
Supports continuation — send follow-up messages to the same agent thread.
"""

import json
import base64
import io
import uuid
from typing import Any

from PIL import Image
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

import os

# ── PostHog LLM Analytics (optional) ──

_posthog_client = None

def _get_posthog_callback(distinct_id: str | None = None, trace_id: str | None = None):
    """Returns a PostHog CallbackHandler if POSTHOG_API_KEY is set, else None."""
    global _posthog_client
    api_key = os.getenv("POSTHOG_API_KEY")
    if not api_key:
        return None
    try:
        if _posthog_client is None:
            from posthog import Posthog
            _posthog_client = Posthog(api_key, host=os.getenv("POSTHOG_HOST", "https://us.i.posthog.com"))
        from posthog.ai.langchain import CallbackHandler
        return CallbackHandler(
            client=_posthog_client,
            distinct_id=distinct_id or "anonymous",
            trace_id=trace_id,
        )
    except Exception:
        return None


# ── Canvas State ──

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


# ── Tool factory ──

def _is_vision_model(model_name: str) -> bool:
    """Check if a model supports image input (base64 previews)."""
    # Ollama local models generally don't support vision
    ollama = set(m.strip() for m in os.getenv("OLLAMA_MODELS", "").split(",") if m.strip())
    if model_name in ollama:
        return False
    # Most cloud models support vision
    return True


def make_tools(canvas: Canvas, vision: bool = True, full_toolset: bool = True):
    """Create agent tools. vision=False omits base64 previews. full_toolset=False drops advanced shape/noise tools."""

    @tool
    def draw_pixel(x: int, y: int, color: int) -> str:
        """Set a single pixel at (x, y) to a palette color index. Use -1 for transparent."""
        return canvas.set_pixel(x, y, color)

    @tool
    def draw_pixels(pixels: list[dict]) -> str:
        """Set multiple pixels at once. Each dict has keys: x, y, color. Use this for efficiency when setting many pixels."""
        errors = []
        drawn = 0
        for p in pixels:
            try:
                x = int(p.get("x", p.get("X", 0)))
                y = int(p.get("y", p.get("Y", 0)))
                c = int(p.get("color", p.get("c", p.get("colour", -1))))
                r = canvas.set_pixel(x, y, c)
                if r.startswith("Error"):
                    errors.append(r)
                else:
                    drawn += 1
            except (KeyError, TypeError, ValueError) as e:
                errors.append(f"Bad pixel data: {p} ({e})")
        return f"Drew {drawn} pixels. {len(errors)} errors: {errors[:3]}" if errors else f"Drew {drawn} pixels."

    @tool
    def fill_rect(x1: int, y1: int, x2: int, y2: int, color: int) -> str:
        """Fill a rectangle from (x1,y1) to (x2,y2) inclusive with a palette color index."""
        return canvas.fill_rect(x1, y1, x2, y2, color)

    @tool
    def fill_row(y: int, x_start: int, x_end: int, color: int) -> str:
        """Fill a horizontal row at y from x_start to x_end inclusive."""
        return canvas.fill_row(y, x_start, x_end, color)

    @tool
    def fill_column(x: int, y_start: int, y_end: int, color: int) -> str:
        """Fill a vertical column at x from y_start to y_end inclusive."""
        return canvas.fill_column(x, y_start, y_end, color)

    @tool
    def draw_line(x1: int, y1: int, x2: int, y2: int, color: int) -> str:
        """Draw a 1-pixel-wide line from (x1,y1) to (x2,y2)."""
        return canvas.draw_line(x1, y1, x2, y2, color)

    @tool
    def draw_circle(cx: int, cy: int, radius: int, color: int, fill: bool = True) -> str:
        """Draw a circle. cx,cy = center, radius = size. fill=True for solid, fill=False for outline only."""
        count = canvas.draw_circle(cx, cy, radius, color, fill)
        return f"Drew {'filled' if fill else 'outline'} circle at ({cx},{cy}) r={radius}, {count}px"

    @tool
    def view_canvas() -> str:
        """View the current canvas. Returns a visual grid where each character is a palette index (0-9, A-Z) and '.' is transparent. Use this to check your work."""
        grid = canvas.to_visual_grid()

        # Color usage summary
        color_counts: dict[int, int] = {}
        for row in canvas.pixels:
            for v in row:
                color_counts[v] = color_counts.get(v, 0) + 1

        summary = []
        for idx, count in sorted(color_counts.items(), key=lambda x: -x[1]):
            if idx == -1:
                summary.append(f". = transparent: {count}px")
            elif 0 <= idx < len(canvas.palette):
                char = str(idx) if idx < 10 else chr(ord("A") + idx - 10)
                summary.append(f"{char} = {idx}({canvas.palette[idx]}): {count}px")

        total = sum(c for i, c in color_counts.items() if i >= 0)

        # Spatial summary: describe each quadrant
        half = canvas.size // 2
        spatial = f"TOP-LEFT: {canvas.region_summary(0, 0, half-1, half-1)} | TOP-RIGHT: {canvas.region_summary(0, half, half-1, canvas.size-1)} | BOTTOM-LEFT: {canvas.region_summary(half, 0, canvas.size-1, half-1)} | BOTTOM-RIGHT: {canvas.region_summary(half, half, canvas.size-1, canvas.size-1)}"

        result = f"{grid}\n\nLEGEND: {', '.join(summary[:12])}\nFilled: {total}/{canvas.size*canvas.size}px\nLAYOUT: {spatial}"

        # Only include base64 preview for vision-capable models
        if vision:
            img_b64 = canvas.to_image_b64(64)
            result += f"\n\n[PREVIEW base64 PNG 64x64]\n{img_b64}"

        return result

    @tool
    def get_pixel(x: int, y: int) -> str:
        """Get the palette index at position (x, y)."""
        v = canvas.get_pixel(x, y)
        name = canvas.palette[v] if 0 <= v < len(canvas.palette) else "transparent"
        return f"({x},{y}) = {v} ({name})"

    @tool
    def finish() -> str:
        """Call this when the sprite is complete and you're satisfied with the result."""
        return "FINISHED"

    @tool
    def noise_fill_rect(x1: int, y1: int, x2: int, y2: int, colors: list[int], seed: int = 42, scale: float = 1.0) -> str:
        """Fill a rectangle with noise-distributed colors. Randomly picks from the color list per pixel based on noise. Use different seeds for variation. Scale controls granularity (higher = finer)."""
        count = canvas.fill_noise(x1, y1, x2, y2, colors, seed, scale)
        return f"Noise-filled rect ({x1},{y1})-({x2},{y2}) with {len(colors)} colors, {count}px"

    # Core tools — always included (8 tools)
    core = [
        draw_pixel, draw_pixels, fill_rect, fill_row, fill_column, draw_line,
        draw_circle, noise_fill_rect,
        view_canvas, get_pixel, finish,
    ]

    if not full_toolset:
        return core

    # Advanced tools — only for capable models

    @tool
    def draw_ellipse(cx: int, cy: int, rx: int, ry: int, color: int, fill: bool = True) -> str:
        """Draw an ellipse. cx,cy = center, rx/ry = horizontal/vertical radius. fill=True for solid."""
        count = canvas.draw_ellipse(cx, cy, rx, ry, color, fill)
        return f"Drew {'filled' if fill else 'outline'} ellipse at ({cx},{cy}) rx={rx} ry={ry}, {count}px"

    @tool
    def draw_triangle(x1: int, y1: int, x2: int, y2: int, x3: int, y3: int, color: int) -> str:
        """Draw a filled triangle with 3 corner points."""
        count = canvas.draw_triangle(x1, y1, x2, y2, x3, y3, color)
        return f"Drew triangle ({x1},{y1})-({x2},{y2})-({x3},{y3}), {count}px"

    @tool
    def draw_rotated_rect(cx: int, cy: int, width: int, height: int, angle: float, color: int) -> str:
        """Draw a filled rotated rectangle. cx,cy = center position. width,height = full dimensions. angle = rotation in degrees (0=horizontal, 45=diagonal, etc)."""
        count = canvas.draw_rotated_rect(cx, cy, width, height, angle, color)
        return f"Drew rotated rect at ({cx},{cy}) {width}x{height} angle={angle}deg, {count}px"

    @tool
    def noise_fill_circle(cx: int, cy: int, radius: int, colors: list[int], seed: int = 42) -> str:
        """Fill a circular area with noise-distributed colors. Good for organic patches, spots, texture within a round area."""
        count = canvas.fill_noise_circle(cx, cy, radius, colors, seed)
        return f"Noise-filled circle at ({cx},{cy}) r={radius} with {len(colors)} colors, {count}px"

    @tool
    def voronoi_fill(x1: int, y1: int, x2: int, y2: int, colors: list[int], num_cells: int = 8, seed: int = 42) -> str:
        """Fill a rectangle with Voronoi cell pattern. Creates organic stone-like, cobblestone, or cellular textures. Each cell gets a color from the list. num_cells controls how many cells (more = smaller cells)."""
        count = canvas.fill_voronoi(x1, y1, x2, y2, colors, num_cells, seed)
        return f"Voronoi-filled rect ({x1},{y1})-({x2},{y2}) with {num_cells} cells, {count}px"

    return core + [draw_ellipse, draw_triangle, draw_rotated_rect, noise_fill_circle, voronoi_fill]


# ── LLM factory ──

OPENAI_MODEL_PREFIXES = ("gpt-", "o1-", "o3-")

# Ollama config
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODELS = set(m.strip() for m in os.getenv("OLLAMA_MODELS", "").split(",") if m.strip())

def _get_llm(model_name: str, temperature: float = 0.7):
    # Ollama models (OpenAI-compatible API)
    if model_name in OLLAMA_MODELS:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            base_url=f"{OLLAMA_URL}/v1",
            api_key="ollama",
        )

    # OpenAI models
    if model_name.startswith(OPENAI_MODEL_PREFIXES):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature)

    # Gemini via API key
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)

    # Gemini via Vertex AI (service account)
    import json as _json
    from langchain_google_vertexai import ChatVertexAI
    sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    project = None
    if sa_path and os.path.exists(sa_path):
        with open(sa_path) as f:
            project = _json.load(f).get("project_id")
    return ChatVertexAI(
        model_name=model_name,
        temperature=temperature,
        project=project,
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
    )


# ── Active sessions (in-memory — keyed by generation_id) ──

_sessions: dict[int, dict] = {}


def _get_or_create_session(gen_id: int, canvas: Canvas, model_name: str):
    """Get existing session or create a new one. Returns (agent, thread_id, canvas)."""
    if gen_id in _sessions:
        s = _sessions[gen_id]
        return s["agent"], s["thread_id"], s["canvas"]

    vision = _is_vision_model(model_name)
    full_toolset = vision  # small local models get the simplified toolset
    tools = make_tools(canvas, vision=vision, full_toolset=full_toolset)
    llm = _get_llm(model_name)
    checkpointer = MemorySaver()
    agent = create_react_agent(llm, tools, checkpointer=checkpointer)
    thread_id = str(uuid.uuid4())

    _sessions[gen_id] = {
        "agent": agent,
        "thread_id": thread_id,
        "canvas": canvas,
        "model": model_name,
    }
    return agent, thread_id, canvas


def cleanup_session(gen_id: int):
    _sessions.pop(gen_id, None)


# ── System prompt ──

AGENT_TYPE_HINTS = {
    "block": "This is a BLOCK TILE. Fill EVERY pixel — no transparency (-1). The tile will be placed in a grid next to copies of itself. Cover the entire canvas with the material.",
    "icon": "This is an ITEM ICON. Draw the object shape and use -1 (transparent) for the background. Keep it compact, chunky, and recognizable. Leave some transparent padding around the edges.",
    "character": "This is a CHARACTER SPRITE. Draw a character on transparent background (-1). Make the silhouette clear and recognizable. Leave transparent padding around the edges.",
    "freeform": "This is a FREEFORM sprite. Use your best judgment for the composition. If the subject is a standalone object or character, use -1 (transparent) for the background. If it's a scene, pattern, or texture, fill the entire canvas.",
}

def build_system_prompt(user_prompt: str, palette: list[str], size: int,
                        style_prompt: str, has_reference: bool, sprite_type: str = "block",
                        model_name: str = "") -> str:
    palette_desc = "\n".join(
        f"  {i} (char {'A' if i >= 10 else str(i) if i < 10 else chr(ord('A') + i - 10)}): {c}"
        if i >= 10 else f"  {i}: {c}"
        for i, c in enumerate(palette)
    )
    vision = _is_vision_model(model_name)
    full_toolset = vision

    # Tool list depends on model capability
    if full_toolset:
        tools_text = """- fill_rect(x1,y1,x2,y2,color) — fill a rectangle
- fill_row(y,x_start,x_end,color) — fill one row
- fill_column(x,y_start,y_end,color) — fill one column
- draw_line(x1,y1,x2,y2,color) — 1px line
- draw_circle(cx,cy,radius,color,fill) — circle (filled or outline)
- draw_ellipse(cx,cy,rx,ry,color,fill) — ellipse
- draw_triangle(x1,y1,x2,y2,x3,y3,color) — filled triangle
- draw_rotated_rect(cx,cy,w,h,angle,color) — rotated rectangle
- draw_pixel(x,y,color) — single pixel
- draw_pixels([{{"x":0,"y":0,"color":1}},...]) — batch pixels
- noise_fill_rect(x1,y1,x2,y2,colors,seed) — random texture fill
- noise_fill_circle(cx,cy,r,colors,seed) — circular noise fill
- voronoi_fill(x1,y1,x2,y2,colors,cells,seed) — cell/stone patterns
- view_canvas() — see the grid (CALL THIS OFTEN)
- get_pixel(x,y) — check one pixel
- finish() — call when done"""
    else:
        tools_text = """- fill_rect(x1,y1,x2,y2,color) — fill a rectangle
- fill_row(y,x_start,x_end,color) — fill one horizontal row
- fill_column(x,y_start,y_end,color) — fill one vertical column
- draw_line(x1,y1,x2,y2,color) — 1px line between two points
- draw_circle(cx,cy,radius,color,fill) — circle (filled or outline)
- draw_pixel(x,y,color) — set a single pixel
- draw_pixels([{{"x":0,"y":0,"color":1}},...]) — set many pixels at once
- noise_fill_rect(x1,y1,x2,y2,colors,seed) — fill area with random mix of colors (for texture)
- view_canvas() — see the grid (CALL THIS OFTEN to check your work)
- get_pixel(x,y) — check one pixel value
- finish() — call when done"""

    grid_explanation = f"""When you call view_canvas, you see a grid like this:
   0123456789ABCDEF    ← column numbers (hex for 10-15)
 0 ................    ← row 0 (all transparent)
 1 ..0000000000....    ← row 1 (color 0 in columns 2-11)
Each character is a palette index: 0-9 = colors 0-9, A-Z = colors 10-35, . = transparent
Read it like a picture: rows go top to bottom (y), columns go left to right (x).""" if size <= 16 else f"""When you call view_canvas, you see a grid. Each character = one pixel.
0-9 = palette colors 0-9, A-Z = colors 10-35, . = transparent.
Rows = y (top to bottom), columns = x (left to right)."""

    return f"""{style_prompt}

You are a pixel artist. You draw on a {size}x{size} canvas using color indices from a palette.

SUBJECT: {user_prompt}

PALETTE:
{palette_desc}
Use -1 for transparent.

{AGENT_TYPE_HINTS.get(sprite_type, AGENT_TYPE_HINTS["block"])}

{"A reference image is attached. Match its shapes and colors in pixel art." if has_reference else ""}

COORDINATE SYSTEM:
- (0,0) = top-left corner
- ({size-1},{size-1}) = bottom-right corner
- x goes RIGHT (columns), y goes DOWN (rows)

{grid_explanation}

TOOLS:
{tools_text}

WORKFLOW:
1. Plan what to draw — think about the shape, then the colors
2. Fill large areas first with fill_rect
3. Call view_canvas to see your progress
4. Add details with draw_pixel or draw_pixels
5. Call view_canvas again to check
6. Use noise_fill_rect to add texture variation if needed
7. Final view_canvas to verify everything looks right
8. Call finish when done

IMPORTANT: Call view_canvas after every few drawing steps. It shows you exactly what the canvas looks like so you can correct mistakes early."""


# ── Run agent (initial or continuation) ──

def run_agent_stream(
    gen_id: int,
    message: str,
    palette: list[str],
    size: int,
    model_name: str,
    style_prompt: str = "",
    sprite_type: str = "block",
    reference_b64: str | None = None,
    on_step: Any = None,
    max_steps: int = 80,
    existing_pixels: list[list[int]] | None = None,
):
    """
    Run the agent or continue an existing session.
    First call creates the session. Subsequent calls continue the conversation.
    """
    is_new = gen_id not in _sessions

    if is_new:
        canvas = Canvas(size, palette, existing_pixels)
        agent, thread_id, canvas = _get_or_create_session(gen_id, canvas, model_name)

        # Build initial message with system prompt + optional reference
        sys_prompt = build_system_prompt(message, palette, size, style_prompt, reference_b64 is not None, sprite_type, model_name)
        user_parts = [{"type": "text", "text": sys_prompt}]
        if reference_b64:
            user_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{reference_b64}"},
            })
        input_message = HumanMessage(content=user_parts)
    else:
        s = _sessions[gen_id]
        agent = s["agent"]
        thread_id = s["thread_id"]
        canvas = s["canvas"]

        # Follow-up: include current canvas state so AI knows what it's editing
        grid = canvas.to_grid_string()
        follow_up = f"""The user wants you to make changes to the current sprite.

CURRENT CANVAS STATE:
{grid}

USER REQUEST: {message}

Use the canvas tools to make the requested changes. Call finish when done."""
        input_message = HumanMessage(content=follow_up)

    config = {"configurable": {"thread_id": thread_id}}

    # Add PostHog callback if configured
    ph_callback = _get_posthog_callback(distinct_id=str(gen_id), trace_id=f"gen_{gen_id}")
    if ph_callback:
        config["callbacks"] = [ph_callback]

    step_count = 0
    finished = False

    # Consume the full stream — don't break early to avoid GeneratorExit in LangSmith
    for chunk in agent.stream(
        {"messages": [input_message]},
        config=config,
        stream_mode="updates",
    ):
        if finished:
            continue  # drain remaining chunks without processing

        for node_name, node_data in chunk.items():
            messages = node_data.get("messages", [])
            for msg in messages:
                step_count += 1

                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    # Agent decided to call a tool — log it but DON'T snapshot pixels yet
                    # (the tool hasn't executed, canvas hasn't changed)
                    for tc in msg.tool_calls:
                        info = f"Tool: {tc['name']}({json.dumps(tc['args'], separators=(',', ':'))})"
                        if on_step:
                            on_step(canvas, "tool_call", info)

                elif hasattr(msg, "content") and isinstance(msg.content, str):
                    content = msg.content.strip()
                    if "FINISHED" in (msg.content or ""):
                        finished = True
                    # Tool results come from the "tools" node — canvas has been updated
                    if node_name == "tools" and on_step:
                        on_step(canvas, "tool_result", content[:200])
                    elif content and on_step:
                        on_step(canvas, "thought", content[:200])

                if step_count >= max_steps:
                    finished = True

    return canvas

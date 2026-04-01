"""
Pixel Studio Agent — LangGraph-based pixel art agent with canvas tools.

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

def make_tools(canvas: Canvas):
    @tool
    def draw_pixel(x: int, y: int, color: int) -> str:
        """Set a single pixel at (x, y) to a palette color index. Use -1 for transparent."""
        return canvas.set_pixel(x, y, color)

    @tool
    def draw_pixels(pixels: list[dict]) -> str:
        """Set multiple pixels at once. Each dict has keys: x, y, color."""
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
    def view_canvas() -> str:
        """View the current canvas state. Returns the pixel index grid, color usage summary, and a base64 PNG preview image of the rendered sprite. Use this to check your work visually."""
        grid = canvas.to_grid_string()
        img_b64 = canvas.to_image_b64(64)

        color_counts: dict[int, int] = {}
        for row in canvas.pixels:
            for v in row:
                color_counts[v] = color_counts.get(v, 0) + 1

        summary = []
        for idx, count in sorted(color_counts.items(), key=lambda x: -x[1]):
            if idx == -1:
                summary.append(f"transparent: {count}px")
            elif 0 <= idx < len(canvas.palette):
                summary.append(f"{idx}({canvas.palette[idx]}): {count}px")

        total = sum(c for i, c in color_counts.items() if i >= 0)
        return f"{grid}\n\nCOLOR USAGE: {', '.join(summary[:12])}\nFilled: {total}/{canvas.size*canvas.size}px\n\n[RENDERED PREVIEW base64 PNG 64x64]\n{img_b64}"

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

    # ── Shape tools ──

    @tool
    def draw_circle(cx: int, cy: int, radius: int, color: int, fill: bool = True) -> str:
        """Draw a circle. cx,cy = center, radius = size. fill=True for solid, fill=False for outline only."""
        count = canvas.draw_circle(cx, cy, radius, color, fill)
        return f"Drew {'filled' if fill else 'outline'} circle at ({cx},{cy}) r={radius}, {count}px"

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

    # ── Noise tools ──

    @tool
    def noise_fill_rect(x1: int, y1: int, x2: int, y2: int, colors: list[int], seed: int = 42, scale: float = 1.0) -> str:
        """Fill a rectangle with noise-distributed colors. Randomly picks from the color list per pixel based on noise. Use different seeds for variation. Scale controls granularity (higher = finer)."""
        count = canvas.fill_noise(x1, y1, x2, y2, colors, seed, scale)
        return f"Noise-filled rect ({x1},{y1})-({x2},{y2}) with {len(colors)} colors, {count}px"

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

    return [
        draw_pixel, draw_pixels, fill_rect, fill_row, fill_column, draw_line,
        draw_circle, draw_ellipse, draw_triangle,
        noise_fill_rect, noise_fill_circle, voronoi_fill,
        view_canvas, get_pixel, finish,
    ]


# ── LLM factory ──

OPENAI_MODEL_PREFIXES = ("gpt-", "o1-", "o3-")

def _get_llm(model_name: str, temperature: float = 0.7):
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
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )


# ── Active sessions (in-memory — keyed by generation_id) ──

_sessions: dict[int, dict] = {}


def _get_or_create_session(gen_id: int, canvas: Canvas, model_name: str):
    """Get existing session or create a new one. Returns (agent, thread_id, canvas)."""
    if gen_id in _sessions:
        s = _sessions[gen_id]
        return s["agent"], s["thread_id"], s["canvas"]

    tools = make_tools(canvas)
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
}

def build_system_prompt(user_prompt: str, palette: list[str], size: int,
                        style_prompt: str, has_reference: bool, sprite_type: str = "block") -> str:
    palette_desc = "\n".join(f"  {i}: {c}" for i, c in enumerate(palette))
    return f"""{style_prompt}

You are a pixel artist working on a {size}x{size} canvas.
You have tools to draw pixels, fill rectangles, draw lines, and view your work.

SUBJECT: {user_prompt}

PALETTE (color indices you can use):
{palette_desc}
Use -1 for transparent pixels.

{AGENT_TYPE_HINTS.get(sprite_type, AGENT_TYPE_HINTS["block"])}

{"A reference concept image is provided. Match its shapes, colors, and composition as closely as possible in pixel art form." if has_reference else ""}

TOOLS AVAILABLE:
- fill_rect, fill_row, fill_column — fill rectangular areas
- draw_circle, draw_ellipse — round shapes (filled or outline)
- draw_triangle — filled triangles
- draw_line — 1px lines
- draw_pixel, draw_pixels — individual pixels
- noise_fill_rect, noise_fill_circle — fill areas with random color distribution (great for texture)
- voronoi_fill — cell/stone-like patterns (great for cobblestone, rocks, organic surfaces)
- view_canvas — see current state (grid + rendered image)
- get_pixel — check a single pixel
- finish — call when done

WORKFLOW:
1. Start by filling the base shape with fill_rect or shapes
2. Add texture with noise_fill_rect or voronoi_fill for natural variation
3. Add detail with individual pixels or draw_pixels
4. Use view_canvas to check your progress periodically
5. Add edge darkening and final polish
6. Use view_canvas one final time to verify
7. Call finish when done

Work methodically. Think about what you're drawing before each action.
The canvas starts fully transparent (-1). Coordinates: (0,0) is top-left, ({size-1},{size-1}) is bottom-right."""


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
        sys_prompt = build_system_prompt(message, palette, size, style_prompt, reference_b64 is not None, sprite_type)
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
                    for tc in msg.tool_calls:
                        info = f"Tool: {tc['name']}({json.dumps(tc['args'], separators=(',', ':'))})"
                        if on_step:
                            on_step(canvas, "tool_call", info)

                elif hasattr(msg, "content") and isinstance(msg.content, str):
                    content = msg.content.strip()
                    if content and on_step:
                        on_step(canvas, "thought", content[:200])
                    if "FINISHED" in (msg.content or ""):
                        finished = True

                if step_count >= max_steps:
                    finished = True

    return canvas

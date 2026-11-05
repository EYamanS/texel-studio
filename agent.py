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
from dotenv import load_dotenv

load_dotenv()


# ── Checkpointer factory ──
#
# In self-hosted mode (no REDIS_URL) we keep the existing MemorySaver — sessions
# live in worker memory, fine for a single process.
#
# In Redis-backed mode the LangGraph thread state is persisted to Redis Stack
# via langgraph-checkpoint-redis, so any worker can resume any thread by ID.
# That kills the worker-affinity routing the old `_sessions` dict required.
#
# RedisSaver.from_conn_string is a context manager. We hold a single open
# instance for the process so it can be reused across run_agent_stream calls.

_redis_checkpointer = None
_redis_checkpointer_ctx = None


def get_checkpointer():
    """Return a process-wide checkpointer. Redis if REDIS_URL set, else Memory."""
    global _redis_checkpointer, _redis_checkpointer_ctx
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        # Single in-memory saver per process is fine for the standalone engine.
        if _redis_checkpointer is None:
            _redis_checkpointer = MemorySaver()
        return _redis_checkpointer
    if _redis_checkpointer is None:
        from langgraph.checkpoint.redis import RedisSaver
        _redis_checkpointer_ctx = RedisSaver.from_conn_string(redis_url)
        _redis_checkpointer = _redis_checkpointer_ctx.__enter__()
        _redis_checkpointer.setup()
    return _redis_checkpointer


def _thread_id_for(gen_id) -> str:
    """Deterministic thread ID per generation. Lets any worker resume any thread."""
    return f"job_{gen_id}"

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

# The canvas lives in pixel_canvas.py so it can be used without the AI dependencies.
from pixel_canvas import Canvas  # noqa: E402,F401  (re-exported for backwards compatibility)


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

# OpenAI / OpenAI-compatible config (Llama.cpp, VLLM, LM Studio, etc.)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODELS_ENV = set(m.strip() for m in os.getenv("OPENAI_MODELS", "").split(",") if m.strip())

def _get_llm(model_name: str, temperature: float = 0.7):
    # Ollama models (OpenAI-compatible API)
    if model_name in OLLAMA_MODELS:
        from langchain_openai import ChatOpenAI
        num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            base_url=f"{OLLAMA_URL}/v1",
            api_key="ollama",
            extra_body={"options": {"num_ctx": num_ctx}},
        )

    # OpenAI / OpenAI-compatible models (custom names registered via OPENAI_MODELS, or standard prefixes)
    if model_name in OPENAI_MODELS_ENV or model_name.startswith(OPENAI_MODEL_PREFIXES):
        from langchain_openai import ChatOpenAI
        kwargs: dict = {"model": model_name, "temperature": temperature}
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
            # Local OpenAI-compatible servers usually don't require a real key, but ChatOpenAI
            # still expects something — fall back to a placeholder if OPENAI_API_KEY is unset.
            if not os.getenv("OPENAI_API_KEY"):
                kwargs["api_key"] = "not-needed"
        return ChatOpenAI(**kwargs)

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


# ── Sessions ──
#
# The old in-memory `_sessions` dict is gone. LangGraph state lives in the
# shared checkpointer (Redis in cloud, Memory for self-host). Canvas pixel
# state is owned by the caller — passed in via `existing_pixels` for
# continuations. Any worker can resume any thread by gen_id.

def cleanup_session(gen_id) -> None:
    """No-op for compatibility. State now lives in the shared checkpointer."""
    return None


def thread_exists(gen_id) -> bool:
    """Return True if a LangGraph thread already exists for this gen_id."""
    cp = get_checkpointer()
    config = {"configurable": {"thread_id": _thread_id_for(gen_id)}}
    try:
        return cp.get(config) is not None
    except Exception:
        return False


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
    gen_id,
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
    cancel_check: Any = None,
):
    """
    Run the agent or continue an existing session.

    First call (no thread for `gen_id`) creates the session and seeds it with the
    full system prompt. Subsequent calls (thread already exists in checkpointer)
    continue the conversation as a chat edit.

    `cancel_check`, if provided, is a zero-arg callable returning True when the
    job has been canceled. The stream loop checks it after every step and exits
    cleanly (drains remaining chunks to avoid GeneratorExit in callbacks).
    """
    # Build the canvas from the caller-provided pixel state. Canvas pixel state
    # lives outside the LangGraph thread (it's owned by the job system, not
    # the conversation). LangGraph just owns the message history.
    canvas = Canvas(size, palette, existing_pixels)
    is_new = not thread_exists(gen_id)
    thread_id = _thread_id_for(gen_id)

    vision = _is_vision_model(model_name)
    full_toolset = vision  # small local models get the simplified toolset
    tools = make_tools(canvas, vision=vision, full_toolset=full_toolset)
    llm = _get_llm(model_name)
    checkpointer = get_checkpointer()
    agent = create_react_agent(llm, tools, checkpointer=checkpointer)

    if is_new:
        sys_prompt = build_system_prompt(message, palette, size, style_prompt, reference_b64 is not None, sprite_type, model_name)
        user_parts = [{"type": "text", "text": sys_prompt}]
        if reference_b64:
            user_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{reference_b64}"},
            })
        input_message = HumanMessage(content=user_parts)
    else:
        # Follow-up: include current canvas state so the agent knows what it's editing
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

        # Cooperative cancel check — if the job was canceled, stop driving the
        # loop but keep draining so callbacks unwind cleanly.
        if cancel_check is not None:
            try:
                if cancel_check():
                    finished = True
                    if on_step:
                        on_step(canvas, "canceled", "Job canceled by user")
                    continue
            except Exception:
                pass

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

#!/usr/bin/env python3
"""
Texel Studio — AI-powered pixel art generator with agent-based painting.

Generates sprites as palette-indexed 2D arrays via Gemini,
constructs images, and iterates through visual feedback loops.
"""

import os
import sys
import json
import time
import base64
import io
import sqlite3
from pathlib import Path
from typing import Optional, List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from PIL import Image
from google import genai

# ── AI Response Schemas ──

class PixelGenerationResponse(BaseModel):
    pixels: List[List[int]] = Field(description="2D array of palette color indices. -1 for transparent.")
    notes: str = Field(description="Brief description of what was drawn.")

class PixelUpdate(BaseModel):
    x: int = Field(description="X coordinate (column)")
    y: int = Field(description="Y coordinate (row)")
    color: int = Field(description="Palette index to set, or -1 for transparent")

class AssessmentResponse(BaseModel):
    approved: bool = Field(description="True if the sprite looks good, false if it needs fixes.")
    reason: str = Field(description="Why it looks good or what needs fixing.")
    updates: List[PixelUpdate] = Field(default=[], description="Specific pixel fixes if not approved.")

# ── Config ──

load_dotenv()
load_dotenv(Path(__file__).parent.parent / "sprite-forge" / ".env")  # fallback to sprite-forge env

# Set GOOGLE_APPLICATION_CREDENTIALS for LangChain/Vertex AI
if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    sa_name = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "service-account.json")
    for candidate in [
        Path(sa_name),
        Path(__file__).parent / sa_name,
        Path(__file__).parent.parent / "sprite-forge" / sa_name,
    ]:
        if candidate.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(candidate.resolve())
            break

GEMINI_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]
OPENAI_MODELS = [
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-4.1-2025-04-14",
    "gpt-4o-mini",
]
ALL_MODELS = GEMINI_MODELS + OPENAI_MODELS
DEFAULT_MODEL = "gemini-3-flash-preview"
IMAGE_GEN_MODELS = [
    "gemini-3.1-flash-image-preview",
]
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image-preview"
REFS_DIR = Path(__file__).parent / "references"
REFS_DIR.mkdir(exist_ok=True)
DB_PATH = Path(__file__).parent / "pixel_studio.db"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Gemini Client ──

def get_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        return genai.Client(api_key=api_key)

    # Try service account — resolve path relative to sprite-forge dir
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_path:
        candidates = [
            Path(sa_path),
            Path(__file__).parent / sa_path,
            Path(__file__).parent.parent / "sprite-forge" / sa_path,
        ]
        for p in candidates:
            if p.exists():
                import json as _json
                with open(p) as f:
                    project_id = _json.load(f).get("project_id", "")
                location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(p.resolve())
                return genai.Client(vertexai=True, project=project_id, location=location)

    raise RuntimeError("No Gemini credentials found. Needs GEMINI_API_KEY or service-account.json")

client = None

def gemini():
    global client
    if client is None:
        client = get_client()
    return client

# ── Database ──

def _has_column(conn, table: str, column: str) -> bool:
    """Check if a column exists in a SQLite table."""
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS palettes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            colors TEXT NOT NULL,
            created_at REAL DEFAULT (unixepoch())
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL,
            system_prompt TEXT,
            colors TEXT,
            size INTEGER NOT NULL,
            model TEXT,
            reference_id TEXT,
            sprite_type TEXT DEFAULT 'block',
            pixel_data TEXT,
            iterations INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            image_path TEXT,
            created_at REAL DEFAULT (unixepoch())
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id INTEGER NOT NULL,
            step TEXT NOT NULL,
            message TEXT,
            created_at REAL DEFAULT (unixepoch()),
            FOREIGN KEY (generation_id) REFERENCES generations(id)
        )
    """)

    # Auto-migrate: add columns that may be missing from older DBs
    if not _has_column(conn, "generations", "colors"):
        conn.execute("ALTER TABLE generations ADD COLUMN colors TEXT")
    if not _has_column(conn, "generations", "sprite_type"):
        conn.execute("ALTER TABLE generations ADD COLUMN sprite_type TEXT DEFAULT 'block'")
    if not _has_column(conn, "generations", "reference_id"):
        conn.execute("ALTER TABLE generations ADD COLUMN reference_id TEXT")

    # Insert default palette if none exist
    if conn.execute("SELECT COUNT(*) FROM palettes").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO palettes (name, colors) VALUES (?, ?)",
            ("Default Earth", json.dumps([
                "#5C3317", "#7B4B2A", "#8B5E3C", "#A0704B",
                "#2D6B12", "#3D8B24", "#4CAF50", "#6ECF5C",
                "#505055", "#68686E", "#7C7C82", "#929298",
                "#C2A65A", "#D4BE6A", "#E8D47A", "#F0E090",
                "#8B6533", "#A67B44", "#C49555", "#D4A866",
                "#C84040", "#D46060", "#4AC8C8", "#80E0E0",
                "#D4A44E", "#E8BC60", "#FFFFFF", "#000000",
            ]))
        )
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Image construction ──

def pixels_to_image(pixel_data: list[list[int]], palette: list[str], size: int) -> Image.Image:
    """Convert 2D array of palette indices to PIL Image."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for y, row in enumerate(pixel_data):
        for x, idx in enumerate(row):
            if idx < 0 or idx >= len(palette):
                continue  # transparent
            hex_color = palette[idx]
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            img.putpixel((x, y), (r, g, b, 255))
    return img

def image_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def upscale_image(img: Image.Image, target: int = 512) -> Image.Image:
    return img.resize((target, target), Image.NEAREST)

# ── Autotile generation ──
# Bitmask: TOP=1, RIGHT=2, BOTTOM=4, LEFT=8
# Mask 15 = fully surrounded (base tile from AI)
# Mask 0 = isolated block (all edges exposed)

def _darken_px(r, g, b, amount):
    return (max(0, int(r * (1 - amount))), max(0, int(g * (1 - amount))), max(0, int(b * (1 - amount))))

def generate_autotile_variant(base_img: Image.Image, mask: int) -> Image.Image:
    """Apply outline, edge shading, and rounded corners for a bitmask variant."""
    size = base_img.width
    img = base_img.copy()
    pixels = img.load()

    top_exposed = (mask & 1) == 0
    right_exposed = (mask & 2) == 0
    bottom_exposed = (mask & 4) == 0
    left_exposed = (mask & 8) == 0

    # Pass 1: Edge shading (highlight top/left, shadow bottom/right)
    band = max(2, size // 5)
    intensity = 0.15
    for y in range(size):
        for x in range(size):
            r, g, b, a = pixels[x, y]
            if a < 25:
                continue
            f = 0.0
            # Note: y=0 is top in PIL (opposite of Unity where y=0 is bottom)
            if top_exposed:
                if y < band:
                    f += intensity * (1 - y / band)
            if left_exposed:
                if x < band:
                    f += intensity * 0.6 * (1 - x / band)
            if bottom_exposed:
                d = size - 1 - y
                if d < band:
                    f -= intensity * (1 - d / band)
            if right_exposed:
                d = size - 1 - x
                if d < band:
                    f -= intensity * 0.6 * (1 - d / band)
            if f != 0:
                r = max(0, min(255, int(r + f * 255)))
                g = max(0, min(255, int(g + f * 255)))
                b = max(0, min(255, int(b + f * 255)))
                pixels[x, y] = (r, g, b, a)

    # Pass 2: Outline — darken exposed edge pixels
    outline_w = max(1, size // 16)
    for y in range(size):
        for x in range(size):
            r, g, b, a = pixels[x, y]
            if a < 25:
                continue
            hit = False
            if top_exposed and y < outline_w:
                hit = True
            if bottom_exposed and y >= size - outline_w:
                hit = True
            if left_exposed and x < outline_w:
                hit = True
            if right_exposed and x >= size - outline_w:
                hit = True
            if hit:
                dr, dg, db = _darken_px(r, g, b, 0.4)
                pixels[x, y] = (dr, dg, db, a)

    # Pass 3: Rounded corners — clear pixels at exposed corners
    radius = max(1, size // 10)
    for y in range(size):
        for x in range(size):
            clear = False
            if top_exposed and left_exposed and x + y < radius:
                clear = True
            if top_exposed and right_exposed and (size - 1 - x) + y < radius:
                clear = True
            if bottom_exposed and left_exposed and x + (size - 1 - y) < radius:
                clear = True
            if bottom_exposed and right_exposed and (size - 1 - x) + (size - 1 - y) < radius:
                clear = True
            if clear:
                pixels[x, y] = (0, 0, 0, 0)

    return img

def generate_tileset(base_img: Image.Image) -> dict[int, Image.Image]:
    """Generate all 16 autotile variants from a base tile (mask 15)."""
    variants = {}
    for mask in range(16):
        variants[mask] = generate_autotile_variant(base_img, mask)
    return variants

# ── Phased generation pipeline ──

DEFAULT_SYSTEM_PROMPT = """You are a pixel art artist.
Style: warm, organic, hand-crafted pixel art. NOT flat or sterile.
Every pixel matters at this scale."""

SPRITE_TYPES = {
    "block": {
        "label": "Block (Tile)",
        "ref_prompt": """Pixel art tile for a 2D side-scrolling sandbox platformer game (like Terraria/Growtopia).
IMPORTANT RULES:
- This is a SQUARE TILE that fills the ENTIRE canvas edge to edge. No empty space, no margins, no background visible.
- Viewed from the SIDE (2D side-scroller perspective), NOT top-down, NOT isometric, NOT 3D.
- The tile must be seamlessly tileable — it will be placed next to copies of itself in a grid.
- Flat front-facing view. No perspective, no depth, no 3D shading.
- Pixel art style with visible individual pixels. Crisp, no anti-aliasing, no smooth gradients.
- The entire square must be filled with the block material.""",
        "agent_hint": "This is a BLOCK TILE. Fill EVERY pixel — no transparency (-1). The tile will be placed in a grid next to copies of itself. Cover the entire canvas with the material.",
        "has_tileset": True,
    },
    "icon": {
        "label": "Item Icon",
        "ref_prompt": """Pixel art item icon for a 2D game inventory.
IMPORTANT RULES:
- Single object centered on a TRANSPARENT background.
- Chunky, bold, readable at small sizes (16x16 to 32x32).
- Clear silhouette — the shape should be instantly recognizable.
- Viewed from the SIDE (2D side-scroller perspective).
- Pixel art style with visible individual pixels.
- The object should NOT fill the entire canvas — leave transparent padding around it.""",
        "agent_hint": "This is an ITEM ICON. Draw the object shape and use -1 (transparent) for the background. Keep it compact, chunky, and recognizable. Leave some transparent padding around the edges.",
        "has_tileset": False,
    },
}

def load_reference_b64(ref_id: str | None) -> str | None:
    """Load a reference image as base64, if it exists."""
    if not ref_id:
        return None
    path = REFS_DIR / ref_id
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def render_grid_overlay(img: Image.Image) -> Image.Image:
    """Add coordinate numbers to an upscaled image for AI position reference."""
    from PIL import ImageDraw, ImageFont
    upscaled = upscale_image(img, 512)
    size = img.width
    cell = 512 // size
    # Create a wider canvas with margins for labels
    margin = 20
    canvas = Image.new("RGBA", (512 + margin, 512 + margin), (10, 10, 10, 255))
    canvas.paste(upscaled, (margin, margin))
    draw = ImageDraw.Draw(canvas)

    # Draw grid lines
    for i in range(size + 1):
        pos = margin + i * cell
        draw.line([(pos, margin), (pos, 512 + margin)], fill=(255, 255, 255, 30), width=1)
        draw.line([(margin, pos), (512 + margin, pos)], fill=(255, 255, 255, 30), width=1)

    # Draw coordinate labels every few pixels
    step = max(1, size // 8)
    for i in range(0, size, step):
        pos = margin + i * cell + cell // 2
        # Column labels (top)
        draw.text((pos - 3, 2), str(i), fill=(200, 200, 200, 180))
        # Row labels (left)
        draw.text((2, pos - 5), str(i), fill=(200, 200, 200, 180))

    return canvas

def build_assessment_context(
    user_prompt: str, palette: list[str], pixel_data: list[list[int]],
    size: int, iteration: int, prev_reason: str | None = None
) -> str:
    """Build rich assessment prompt with full context and text pixel grid."""
    palette_desc = "\n".join(f"  {i}: {c}" for i, c in enumerate(palette))

    # Compact text representation of current pixels
    grid_text = "\n".join(
        " ".join(f"{v:>3}" for v in row) for row in pixel_data
    )

    context = f"""You are reviewing a {size}x{size} pixel art sprite for a 2D game.

ORIGINAL REQUEST: {user_prompt}

PALETTE:
{palette_desc}

CURRENT PIXEL GRID (row, col — each number is a palette index, -1 = transparent):
{grid_text}

An upscaled image with grid coordinates is attached for visual reference.
The numbers along the top and left edges of the image are column (x) and row (y) coordinates.

This is assessment round {iteration}."""

    if prev_reason:
        context += f"\n\nPREVIOUS ASSESSMENT said: {prev_reason}"

    context += """

Check:
1. Does the shape match the requested object?
2. Are colors appropriate for the material?
3. Are there stray pixels, wrong colors, or broken patterns?
4. Does texture variation look natural (not random noise)?

If it looks good, approve it.
If not, provide SPECIFIC pixel fixes — use the grid coordinates (x=column, y=row) and palette indices you can see above."""

    return context

DIRECT_PROMPT_TEMPLATE = """TASK: Generate a {size}x{size} pixel art sprite.

PALETTE (use these indices, -1 = transparent):
{palette_desc}

USER REQUEST: {user_prompt}

Output exactly {size} rows of {size} integers each.
Every integer is a palette index (0 to {palette_max}) or -1 for transparent.
Think carefully about each pixel. This is {size}x{size} — every pixel matters."""

def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

# ── Redis (optional — for queue-based worker mode) ──

REDIS_URL = os.getenv("REDIS_URL")
_redis = None

def get_redis():
    global _redis
    if _redis is None and REDIS_URL:
        import redis as _redis_mod
        _redis = _redis_mod.from_url(REDIS_URL, decode_responses=True)
    return _redis

def _sse_from_redis(job_id: str):
    """Subscribe to a Redis pub/sub channel and yield SSE events."""
    import redis as _redis_mod
    sub = _redis_mod.from_url(REDIS_URL, decode_responses=True).pubsub()
    sub.subscribe(f"texel:events:{job_id}")
    try:
        for msg in sub.listen():
            if msg["type"] != "message":
                continue
            data = msg["data"]
            if data == "__done__":
                break
            yield data
    finally:
        sub.unsubscribe()
        sub.close()

def _wait_for_redis_result(job_id: str, timeout: int = 120):
    """Subscribe to a Redis result channel and wait for a single response."""
    import redis as _redis_mod
    sub = _redis_mod.from_url(REDIS_URL, decode_responses=True).pubsub()
    sub.subscribe(f"texel:result:{job_id}")
    try:
        for msg in sub.listen():
            if msg["type"] != "message":
                continue
            return json.loads(msg["data"])
    finally:
        sub.unsubscribe()
        sub.close()
    return {"error": "Timed out"}

def _run_agent_sse(generation_id: int, message: str, is_continuation: bool = False, colors: list[str] | None = None):
    """Shared SSE generator for initial generation and chat continuation."""
    import threading
    import queue as queue_mod
    from agent import run_agent_stream as agent_run, cleanup_session

    db = get_db()
    gen = db.execute("SELECT * FROM generations WHERE id = ?", (generation_id,)).fetchone()
    if not gen:
        yield sse_event("error", {"message": "Generation not found"})
        return

    palette = colors if colors else ["#c8a44e"]
    size = gen["size"]
    model = gen["model"] or DEFAULT_MODEL
    sprite_type = gen["sprite_type"] or "block"
    type_config = SPRITE_TYPES.get(sprite_type, SPRITE_TYPES["block"])
    system_prompt = gen["system_prompt"] or DEFAULT_SYSTEM_PROMPT
    ref_b64 = load_reference_b64(gen["reference_id"]) if not is_continuation else None

    if not is_continuation:
        db.execute("INSERT INTO generation_logs (generation_id, step, message) VALUES (?, ?, ?)",
                   (generation_id, "start", f"Agent mode: {size}x{size} with {model}"))
        db.execute("UPDATE generations SET status = 'generating' WHERE id = ?", (generation_id,))
        db.commit()
        yield sse_event("log", {"step": "start", "message": f"Agent painting {size}x{size} with {model}..."})
    else:
        db.execute("INSERT INTO generation_logs (generation_id, step, message) VALUES (?, ?, ?)",
                   (generation_id, "chat", f"Edit request: {message[:100]}"))
        db.commit()
        yield sse_event("log", {"step": "chat", "message": f"Editing: {message[:100]}..."})

    # Load existing pixels for continuation
    existing_pixels = None
    if is_continuation and gen["pixel_data"]:
        existing_pixels = json.loads(gen["pixel_data"])

    event_queue = queue_mod.Queue()
    step_count = [0]
    last_pixel_step = [0]

    def on_step(canvas, step_type, msg):
        step_count[0] += 1
        event_queue.put(sse_event("log", {"step": f"{step_type}_{step_count[0]}", "message": msg}))

        # Always send pixels on view_canvas, otherwise every 2 tool calls
        is_view = "view_canvas" in msg
        if step_type == "tool_call" and (is_view or step_count[0] - last_pixel_step[0] >= 2):
            last_pixel_step[0] = step_count[0]
            px_copy = [row[:] for row in canvas.pixels]
            event_queue.put(sse_event("pixels", {
                "pixel_data": px_copy, "iteration": step_count[0],
                "notes": f"Step {step_count[0]}", "gen_id": generation_id,
            }))

    def worker():
        try:
            canvas = agent_run(
                gen_id=generation_id,
                message=message,
                palette=palette,
                size=size,
                model_name=model,
                style_prompt=system_prompt,
                sprite_type=sprite_type,
                reference_b64=ref_b64,
                on_step=on_step,
                existing_pixels=existing_pixels,
            )

            pixel_data = [row[:] for row in canvas.pixels]
            event_queue.put(sse_event("pixels", {
                "pixel_data": pixel_data, "iteration": step_count[0],
                "notes": "Agent finished", "gen_id": generation_id,
            }))

            db2 = get_db()
            db2.execute("UPDATE generations SET pixel_data = ?, iterations = ? WHERE id = ?",
                       (json.dumps(pixel_data), step_count[0], generation_id))

            final_img = canvas.to_image()
            filename = f"gen_{generation_id}_{size}x{size}.png"
            final_img.save(OUTPUT_DIR / filename)
            upscale_image(final_img, 512).save(OUTPUT_DIR / f"gen_{generation_id}_preview.png")

            db2.execute("UPDATE generations SET status = 'complete', image_path = ? WHERE id = ?",
                       (filename, generation_id))
            db2.commit()
            db2.close()

            event_queue.put(sse_event("log", {"step": "complete", "message": f"Done in {step_count[0]} steps"}))
            event_queue.put(sse_event("complete", {"id": generation_id, "image_path": filename}))

        except Exception as e:
            db2 = get_db()
            db2.execute("UPDATE generations SET status = 'error' WHERE id = ?", (generation_id,))
            db2.execute("INSERT INTO generation_logs (generation_id, step, message) VALUES (?, ?, ?)",
                       (generation_id, "error", str(e)))
            db2.commit()
            db2.close()
            event_queue.put(sse_event("error", {"message": str(e)}))
        finally:
            event_queue.put(None)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    while True:
        try:
            ev = event_queue.get(timeout=300)  # 5 min per event
            if ev is None:
                break
            yield ev
        except queue_mod.Empty:
            yield sse_event("error", {"message": "Agent timed out (5 min without response)"})
            break

    db.close()

# ── FastAPI ──

app = FastAPI(title="Texel Studio")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API key auth — set API_KEY env var to enable
_API_KEY = os.getenv("API_KEY")

if _API_KEY:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class ApiKeyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Skip auth for health check
            if request.url.path == "/health":
                return await call_next(request)
            key = request.headers.get("x-api-key") or request.query_params.get("api_key")
            if key != _API_KEY:
                return JSONResponse({"error": "Invalid or missing API key"}, status_code=401)
            return await call_next(request)

    app.add_middleware(ApiKeyMiddleware)

# API models
class PaletteCreate(BaseModel):
    name: str
    colors: list[str]

class PaletteUpdate(BaseModel):
    name: Optional[str] = None
    colors: Optional[list[str]] = None

class ReferenceRequest(BaseModel):
    prompt: str
    feedback: Optional[str] = None
    model: Optional[str] = None
    sprite_type: str = "block"

class GenerateRequest(BaseModel):
    prompt: str
    colors: list[str]
    size: int = 16
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    reference_id: Optional[str] = None
    sprite_type: str = "block"

class ManualPixelUpdate(BaseModel):
    generation_id: int
    updates: list[dict]  # [{x, y, color}]

# ── Palette endpoints ──

@app.get("/api/palettes")
def list_palettes():
    db = get_db()
    rows = db.execute("SELECT * FROM palettes ORDER BY created_at DESC").fetchall()
    db.close()
    return [{"id": r["id"], "name": r["name"], "colors": json.loads(r["colors"]), "created_at": r["created_at"]} for r in rows]

@app.post("/api/palettes")
def create_palette(data: PaletteCreate):
    db = get_db()
    cur = db.execute("INSERT INTO palettes (name, colors) VALUES (?, ?)",
                     (data.name, json.dumps(data.colors)))
    db.commit()
    pid = cur.lastrowid
    db.close()
    return {"id": pid, "name": data.name, "colors": data.colors}

@app.put("/api/palettes/{palette_id}")
def update_palette(palette_id: int, data: PaletteUpdate):
    db = get_db()
    if data.name:
        db.execute("UPDATE palettes SET name = ? WHERE id = ?", (data.name, palette_id))
    if data.colors:
        db.execute("UPDATE palettes SET colors = ? WHERE id = ?", (json.dumps(data.colors), palette_id))
    db.commit()
    row = db.execute("SELECT * FROM palettes WHERE id = ?", (palette_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(404)
    return {"id": row["id"], "name": row["name"], "colors": json.loads(row["colors"])}

@app.delete("/api/palettes/{palette_id}")
def delete_palette(palette_id: int):
    db = get_db()
    db.execute("DELETE FROM palettes WHERE id = ?", (palette_id,))
    db.commit()
    db.close()
    return {"ok": True}

# ── Reference image endpoints ──

@app.post("/api/reference")
async def generate_reference(data: ReferenceRequest):
    """Generate a concept/reference image using image generation model."""
    rd = get_redis()
    if rd:
        import uuid as _uuid
        job_id = str(_uuid.uuid4())
        rd.lpush("texel:jobs", json.dumps({
            "type": "reference",
            "job_id": job_id,
            "prompt": data.prompt,
            "feedback": data.feedback,
            "model": data.model,
            "sprite_type": data.sprite_type,
        }))
        result = _wait_for_redis_result(job_id)
        if "error" in result:
            return JSONResponse(result, status_code=500)
        return result

    try:
        type_config = SPRITE_TYPES.get(data.sprite_type, SPRITE_TYPES["block"])
        ref_prompt = f"{data.prompt}\n\n{type_config['ref_prompt']}"
        if data.feedback:
            ref_prompt += f"\n\nRevision feedback: {data.feedback}"

        img_model = data.model if data.model in IMAGE_GEN_MODELS else DEFAULT_IMAGE_MODEL
        try:
            # Try with response_modalities for Vertex AI
            response = gemini().models.generate_content(
                model=img_model,
                contents=[ref_prompt],
                config=genai.types.GenerateContentConfig(
                    response_modalities=["Image", "Text"],
                ),
            )
        except Exception:
            # Fallback without response_modalities
            response = gemini().models.generate_content(
                model=img_model,
                contents=[ref_prompt],
            )

        for part in response.parts:
            if part.inline_data is not None:
                ref_id = f"ref_{int(time.time())}_{hash(data.prompt) & 0xFFFF:04x}.png"
                # Try as_image first, fall back to raw bytes
                try:
                    img = part.as_image()
                    img.save(REFS_DIR / ref_id)
                except Exception:
                    img_bytes = part.inline_data.data
                    if isinstance(img_bytes, str):
                        img_bytes = base64.b64decode(img_bytes)
                    with open(REFS_DIR / ref_id, "wb") as f:
                        f.write(img_bytes)
                return {"reference_id": ref_id}

        # Some models return image as the candidate's content differently
        if hasattr(response, 'candidates') and response.candidates:
            for candidate in response.candidates:
                if hasattr(candidate, 'content') and candidate.content:
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            ref_id = f"ref_{int(time.time())}_{hash(data.prompt) & 0xFFFF:04x}.png"
                            img_bytes = part.inline_data.data
                            if isinstance(img_bytes, str):
                                img_bytes = base64.b64decode(img_bytes)
                            with open(REFS_DIR / ref_id, "wb") as f:
                                f.write(img_bytes)
                            return {"reference_id": ref_id}

        return JSONResponse({"error": "No image in response. Model may not support image generation."}, status_code=500)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[REFERENCE ERROR]\n{tb}")
        return JSONResponse({"error": f"{str(e)}\n\n{tb}"}, status_code=500)

@app.post("/api/reference/upload")
async def upload_reference(request: Request):
    """Upload a local image as reference."""
    from fastapi import UploadFile
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(400, "No file uploaded")
        data = await file.read()
    else:
        data = await request.body()

    if not data:
        raise HTTPException(400, "Empty file")

    ref_id = f"ref_{int(time.time())}_{hash(data) & 0xFFFF:04x}.png"

    # Convert to PNG if needed
    try:
        img = Image.open(io.BytesIO(data))
        img.save(REFS_DIR / ref_id, "PNG")
    except Exception:
        # Save raw if it's already a valid image format
        with open(REFS_DIR / ref_id, "wb") as f:
            f.write(data)

    return {"reference_id": ref_id}

@app.get("/api/reference/{ref_id}")
def serve_reference(ref_id: str):
    path = REFS_DIR / ref_id
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")

# ── Generation endpoints ──

@app.get("/api/generations")
def list_generations():
    db = get_db()
    rows = db.execute("""
        SELECT * FROM generations
        ORDER BY created_at DESC
        LIMIT 50
    """).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.delete("/api/generations/{gen_id}")
def delete_generation(gen_id: int):
    db = get_db()
    gen = db.execute("SELECT image_path FROM generations WHERE id = ?", (gen_id,)).fetchone()
    if gen and gen["image_path"]:
        # Delete image files
        for suffix in ["", "_preview"]:
            p = OUTPUT_DIR / gen["image_path"].replace(".png", f"{suffix}.png")
            if p.exists():
                p.unlink()
    db.execute("DELETE FROM generation_logs WHERE generation_id = ?", (gen_id,))
    db.execute("DELETE FROM generations WHERE id = ?", (gen_id,))
    db.commit()
    db.close()
    return {"ok": True}

@app.get("/api/generations/{gen_id}")
def get_generation(gen_id: int):
    db = get_db()
    gen = db.execute("SELECT * FROM generations WHERE id = ?", (gen_id,)).fetchone()
    if not gen:
        raise HTTPException(404)
    logs = db.execute("SELECT * FROM generation_logs WHERE generation_id = ? ORDER BY created_at",
                      (gen_id,)).fetchall()
    db.close()
    return {
        **dict(gen),
        "pixel_data": json.loads(gen["pixel_data"]) if gen["pixel_data"] else None,
        "colors": json.loads(gen["colors"]) if gen["colors"] else None,
        "logs": [dict(l) for l in logs],
    }

@app.post("/api/generate")
async def start_generation(data: GenerateRequest):
    if data.size not in (8, 16, 32, 64):
        raise HTTPException(400, "Size must be 8, 16, 32, or 64")
    if not data.colors:
        raise HTTPException(400, "Colors array is required")

    db = get_db()
    model = data.model if data.model in GEMINI_MODELS else DEFAULT_MODEL
    cur = db.execute(
        "INSERT INTO generations (prompt, system_prompt, colors, size, model, reference_id, sprite_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (data.prompt, data.system_prompt, json.dumps(data.colors), data.size, model, data.reference_id, data.sprite_type),
    )
    gen_id = cur.lastrowid
    db.commit()
    db.close()

    rd = get_redis()
    if rd:
        import uuid as _uuid
        job_id = str(_uuid.uuid4())
        rd.lpush("texel:jobs", json.dumps({
            "type": "generate",
            "job_id": job_id,
            "gen_id": gen_id,
            "message": data.prompt,
            "colors": data.colors,
            "size": data.size,
            "model": model,
            "sprite_type": data.sprite_type,
            "system_prompt": data.system_prompt,
            "reference_id": data.reference_id,
            "is_continuation": False,
        }))
        return StreamingResponse(
            _sse_from_redis(job_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Fallback: in-memory (no Redis, self-hosted)
    return StreamingResponse(
        _run_agent_sse(gen_id, data.prompt, colors=data.colors),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/api/generations/{gen_id}/update_pixels")
def manual_pixel_update(gen_id: int, data: ManualPixelUpdate):
    db = get_db()
    gen = db.execute("SELECT * FROM generations WHERE id = ?", (gen_id,)).fetchone()
    if not gen or not gen["pixel_data"]:
        raise HTTPException(404)

    pixel_data = json.loads(gen["pixel_data"])
    palette = json.loads(gen["colors"]) if gen["colors"] else ["#c8a44e"]
    size = gen["size"]

    for u in data.updates:
        x, y, c = u.get("x", 0), u.get("y", 0), u.get("color", -1)
        if 0 <= y < size and 0 <= x < size:
            pixel_data[y][x] = c

    # Rebuild image
    img = pixels_to_image(pixel_data, palette, size)
    filename = f"gen_{gen_id}_{size}x{size}.png"
    img.save(OUTPUT_DIR / filename)
    upscale_image(img, 512).save(OUTPUT_DIR / f"gen_{gen_id}_preview.png")

    db.execute("UPDATE generations SET pixel_data = ? WHERE id = ?",
               (json.dumps(pixel_data), gen_id))
    db.commit()
    db.close()
    return {"ok": True, "pixel_data": pixel_data}

# ── Image serving ──

@app.get("/api/images/{filename}")
def serve_image(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")

# ── Settings ──

# ── Chat (continue agent session) ──

class ChatRequest(BaseModel):
    generation_id: int
    message: str

@app.post("/api/chat")
async def chat_with_agent(data: ChatRequest):
    db = get_db()
    gen = db.execute("SELECT * FROM generations WHERE id = ?", (data.generation_id,)).fetchone()
    db.close()
    if not gen:
        raise HTTPException(404)

    rd = get_redis()
    if rd:
        import uuid as _uuid
        job_id = str(_uuid.uuid4())

        # Route to the worker that owns this session
        worker_id = rd.get(f"texel:sessions:{data.generation_id}")
        queue_name = f"texel:jobs:{worker_id}" if worker_id else "texel:jobs"

        # Get colors from the generation
        colors = json.loads(gen["colors"]) if gen["colors"] else ["#c8a44e"]

        pixel_data = json.loads(gen["pixel_data"]) if gen["pixel_data"] else None
        rd.lpush(queue_name, json.dumps({
            "type": "chat",
            "job_id": job_id,
            "gen_id": data.generation_id,
            "message": data.message,
            "colors": colors,
            "size": gen["size"],
            "model": gen["model"],
            "sprite_type": gen["sprite_type"] or "block",
            "system_prompt": gen["system_prompt"],
            "pixel_data": pixel_data,
            "is_continuation": True,
        }))
        return StreamingResponse(
            _sse_from_redis(job_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        _run_agent_sse(data.generation_id, data.message, is_continuation=True),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── Finalize (skip remaining iterations) ──

@app.post("/api/generations/{gen_id}/finalize")
def finalize_generation(gen_id: int):
    db = get_db()
    gen = db.execute("SELECT * FROM generations WHERE id = ?", (gen_id,)).fetchone()
    if not gen or not gen["pixel_data"]:
        raise HTTPException(404)

    palette = json.loads(gen["colors"]) if gen["colors"] else ["#c8a44e"]
    pixel_data = json.loads(gen["pixel_data"])
    size = gen["size"]

    # Save current state as final
    final_img = pixels_to_image(pixel_data, palette, size)
    filename = f"gen_{gen_id}_{size}x{size}.png"
    final_img.save(OUTPUT_DIR / filename)
    upscale_image(final_img, 512).save(OUTPUT_DIR / f"gen_{gen_id}_preview.png")

    db.execute("UPDATE generations SET status = 'complete', image_path = ? WHERE id = ?",
               (filename, gen_id))
    db.execute("INSERT INTO generation_logs (generation_id, step, message) VALUES (?, ?, ?)",
               (gen_id, "finalized", "Manually finalized — skipped remaining iterations"))
    db.commit()
    db.close()
    return {"ok": True, "id": gen_id, "image_path": filename}

# ── Tileset generation ──

class TilesetRequest(BaseModel):
    generation_id: int
    name: str  # e.g. "Dirt" — files will be Dirt_00.png through Dirt_15.png

@app.post("/api/tileset")
def generate_tileset_endpoint(data: TilesetRequest):
    db = get_db()
    gen = db.execute("SELECT * FROM generations WHERE id = ?", (data.generation_id,)).fetchone()
    if not gen or not gen["pixel_data"]:
        raise HTTPException(404, "Generation not found or has no pixel data")

    palette = json.loads(gen["colors"]) if gen["colors"] else ["#c8a44e"]
    pixel_data = json.loads(gen["pixel_data"])
    size = gen["size"]
    db.close()

    # Build base image (this is variant 15 — fully surrounded)
    base_img = pixels_to_image(pixel_data, palette, size)

    # Generate all 16 variants
    variants = generate_tileset(base_img)

    # Save to output/tilesets/<name>/
    tileset_dir = OUTPUT_DIR / "tilesets" / data.name
    tileset_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for mask in range(16):
        filename = f"{data.name}_{mask:02d}.png"
        variants[mask].save(tileset_dir / filename)
        files.append(filename)

    return {
        "name": data.name,
        "path": str(tileset_dir),
        "files": files,
        "count": len(files),
    }

@app.get("/api/tileset/{name}/{filename}")
def serve_tileset_file(name: str, filename: str):
    path = OUTPUT_DIR / "tilesets" / name / filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")

@app.get("/api/tileset/{name}")
def get_tileset_preview(name: str):
    tileset_dir = OUTPUT_DIR / "tilesets" / name
    if not tileset_dir.exists():
        raise HTTPException(404)
    files = sorted([f.name for f in tileset_dir.glob("*.png")])
    return {"name": name, "files": files}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/settings")
def get_settings():
    return {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "models": ALL_MODELS,
        "default_model": DEFAULT_MODEL,
        "image_models": IMAGE_GEN_MODELS,
        "default_image_model": DEFAULT_IMAGE_MODEL,
        "sprite_types": {k: {"label": v["label"], "has_tileset": v["has_tileset"]} for k, v in SPRITE_TYPES.items()},
    }

# ── Static files (UI) ──

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8500"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=os.getenv("RAILWAY_ENVIRONMENT") is None)

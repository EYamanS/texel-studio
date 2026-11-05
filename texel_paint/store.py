"""
Storage layer: the SQLite database and output folder shared with the Texel Studio web app.

A *design* is a row in `generations`. Canvases are always stored as a square grid of `size`; a design may
declare a smaller usable rectangle (`width` x `height`, top-left aligned) for non-square sprites such as
cards (52x72). Everything outside the rectangle is discarded on save and exports are cropped to it.

Environment:
    TEXEL_HOME   folder that holds pixel_studio.db and output/ (default: the repository root)
"""

import json
import os
import sqlite3
from pathlib import Path

from PIL import Image

from pixel_canvas import Canvas
from texel_paint.colors import to_alpha, to_rgb

ROOT = Path(os.environ.get("TEXEL_HOME") or Path(__file__).resolve().parent.parent)
DB_PATH = ROOT / "pixel_studio.db"
OUTPUT = ROOT / "output"
WORK = ROOT / "paint_work"                  # undo snapshots, stamps, macros, previews (git-ignored)
SOURCE_NAME = "texel-paint"                 # stored in generations.model so the UI can show where a design came from
MAX_UNDO = 30


def ensure_dirs() -> None:
    OUTPUT.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the tables if the web app has not run yet and add the columns newer versions need."""
    conn.execute("""CREATE TABLE IF NOT EXISTS palettes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, colors TEXT NOT NULL,
        created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS generations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, prompt TEXT NOT NULL, system_prompt TEXT, colors TEXT,
        size INTEGER NOT NULL, model TEXT, reference_id TEXT, sprite_type TEXT DEFAULT 'block',
        pixel_data TEXT, iterations INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', image_path TEXT,
        created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS generation_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id INTEGER NOT NULL, step TEXT NOT NULL,
        message TEXT, created_at REAL DEFAULT (unixepoch()),
        FOREIGN KEY (generation_id) REFERENCES generations(id))""")
    for column, ddl in (("colors", "TEXT"), ("sprite_type", "TEXT DEFAULT 'block'"), ("reference_id", "TEXT"),
                        ("width", "INTEGER"), ("height", "INTEGER")):
        if not _has_column(conn, "generations", column):
            conn.execute(f"ALTER TABLE generations ADD COLUMN {column} {ddl}")
    conn.commit()


# ───────────────────────── Canvas with usable rectangle ─────────────────────────

class PaintCanvas(Canvas):
    """Canvas plus the design id and the usable rectangle (width x height, top-left)."""

    def __init__(self, size, palette, pixels=None, width=None, height=None, gid=None):
        super().__init__(size, palette, pixels)
        self.width = min(width or size, size)
        self.height = min(height or size, size)
        self.gid = gid

    @property
    def is_rect(self) -> bool:
        return (self.width, self.height) != (self.size, self.size)

    def clip_to_rect(self) -> None:
        """Discard everything outside the usable rectangle."""
        for y in range(self.size):
            for x in range(self.size):
                if x >= self.width or y >= self.height:
                    self.pixels[y][x] = -1

    def to_image(self, crop: bool = True) -> Image.Image:
        """RGBA image. Palette colors may carry alpha as '#rrggbbaa'. Cropped to the usable rectangle."""
        img = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        for y, row in enumerate(self.pixels):
            for x, idx in enumerate(row):
                if 0 <= idx < len(self.palette):
                    color = self.palette[idx]
                    img.putpixel((x, y), to_rgb(color) + (to_alpha(color),))
        return img.crop((0, 0, self.width, self.height)) if crop else img


# ───────────────────────── Palettes ─────────────────────────

def list_palettes() -> list[tuple[int, str, list[str]]]:
    db = connect()
    rows = db.execute("SELECT id, name, colors FROM palettes ORDER BY id").fetchall()
    db.close()
    return [(r["id"], r["name"], json.loads(r["colors"])) for r in rows]


def save_palette(name: str, colors: list[str]) -> int:
    db = connect()
    cur = db.execute("INSERT INTO palettes (name, colors) VALUES (?, ?)", (name, json.dumps(colors)))
    db.commit()
    db.close()
    return cur.lastrowid


# ───────────────────────── Designs ─────────────────────────

def create(prompt: str, size: int = 16, sprite_type: str = "block", colors: list[str] | None = None,
           palette_id: int | None = None, pixels: list[list[int]] | None = None,
           width: int | None = None, height: int | None = None) -> int:
    """Create a design and return its id. `colors=[]` starts with an empty palette (colors are added as you paint)."""
    ensure_dirs()
    if colors is None:
        palettes = list_palettes()
        chosen = next((p for p in palettes if p[0] == palette_id), palettes[0]) if palettes else None
        colors = chosen[2] if chosen else ["#000000", "#ffffff"]
    canvas = PaintCanvas(size, colors, pixels, width, height)
    db = connect()
    cur = db.execute(
        "INSERT INTO generations (prompt, system_prompt, colors, size, model, sprite_type, pixel_data, status, width, height) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'generating', ?, ?)",
        (prompt, "painted with texel_paint", json.dumps(colors), size, SOURCE_NAME, sprite_type,
         json.dumps(canvas.pixels), canvas.width if canvas.is_rect else None, canvas.height if canvas.is_rect else None))
    db.commit()
    gid = cur.lastrowid
    db.close()
    return gid


def load(gid: int) -> PaintCanvas:
    db = connect()
    row = db.execute("SELECT * FROM generations WHERE id = ?", (gid,)).fetchone()
    db.close()
    if not row:
        raise ValueError(f"Design {gid} not found")
    return PaintCanvas(row["size"], json.loads(row["colors"]),
                       json.loads(row["pixel_data"]) if row["pixel_data"] else None,
                       row["width"], row["height"], gid)


def find_by_name(name: str, size: int) -> int | None:
    """Id of the newest texel_paint design with this exact prompt and canvas size (used by batch to overwrite)."""
    db = connect()
    row = db.execute("SELECT id FROM generations WHERE prompt = ? AND model = ? AND size = ? ORDER BY id DESC LIMIT 1",
                     (name, SOURCE_NAME, size)).fetchone()
    db.close()
    return row["id"] if row else None


def save(gid: int, canvas: PaintCanvas, note: str = "") -> str:
    """Write pixels, palette and PNG files, and log the step. Returns the PNG file name."""
    ensure_dirs()
    canvas.clip_to_rect()
    img = canvas.to_image()
    filename = f"gen_{gid}_{canvas.width}x{canvas.height}.png"
    img.save(OUTPUT / filename)
    scale = max(1, 512 // max(img.width, img.height))
    img.resize((img.width * scale, img.height * scale), Image.NEAREST).save(OUTPUT / f"gen_{gid}_preview.png")
    db = connect()
    db.execute("UPDATE generations SET pixel_data = ?, colors = ?, width = ?, height = ?, iterations = iterations + 1, "
               "status = 'complete', image_path = ? WHERE id = ?",
               (json.dumps(canvas.pixels), json.dumps(canvas.palette),
                canvas.width if canvas.is_rect else None, canvas.height if canvas.is_rect else None, filename, gid))
    db.execute("INSERT INTO generation_logs (generation_id, step, message) VALUES (?, ?, ?)",
               (gid, SOURCE_NAME, note or "saved"))
    db.commit()
    db.close()
    return filename


def reset(gid: int, canvas: PaintCanvas, note: str = "reset") -> None:
    """Replace a design with an empty canvas of the same id (batch mode re-runs overwrite instead of piling up)."""
    save(gid, canvas, note)


# ───────────────────────── Undo ─────────────────────────

def _snapshots(gid: int) -> list[Path]:
    return sorted(WORK.glob(f"snap_{gid}_*.json"), key=lambda p: int(p.stem.rsplit("_", 1)[1]))


def snapshot(gid: int, canvas: PaintCanvas) -> None:
    ensure_dirs()
    files = _snapshots(gid)
    index = int(files[-1].stem.rsplit("_", 1)[1]) + 1 if files else 1
    (WORK / f"snap_{gid}_{index}.json").write_text(json.dumps({"pixels": canvas.pixels, "colors": canvas.palette}))
    for old in files[: -(MAX_UNDO - 1)]:
        old.unlink()


def undo(gid: int) -> bool:
    files = _snapshots(gid)
    if not files:
        return False
    canvas = load(gid)
    data = json.loads(files[-1].read_text())
    canvas.pixels, canvas.palette = data["pixels"], data["colors"]
    files[-1].unlink()
    save(gid, canvas, "undo")
    return True

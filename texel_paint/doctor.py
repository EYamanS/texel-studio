"""`doctor` (setup check with next steps) and `serve` (start the web app on localhost)."""

import shutil
import sys
import urllib.request

from pathlib import Path

from texel_paint import store

MIN_PYTHON = (3, 10)
CODE_DIR = Path(__file__).resolve().parent.parent      # where server.py, static/ and frontend/ live (not TEXEL_HOME)


def _module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _server_up(port: int = 8500) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def run() -> int:
    """Print a checklist; returns 0 if you can paint, 1 if something essential is missing."""
    ok = True
    rows: list[tuple[str, bool, str]] = []

    python_ok = sys.version_info >= MIN_PYTHON
    rows.append(("Python >= %d.%d" % MIN_PYTHON, python_ok, sys.version.split()[0]))
    pillow = _module("PIL")
    rows.append(("Pillow (painting)", pillow, "" if pillow else "pip install Pillow"))
    try:
        store.ensure_dirs()
        store.connect().close()
        database = True
        detail = str(store.DB_PATH)
    except Exception as exc:
        database, detail = False, f"cannot open database: {exc}"
    rows.append(("Database + output folder", database, detail))
    ok = python_ok and pillow and database

    web_deps = all(_module(m) for m in ("fastapi", "uvicorn", "dotenv"))
    rows.append(("Web app packages (fastapi, uvicorn ...)", web_deps, "" if web_deps else "pip install -r requirements.txt"))
    built = (CODE_DIR / "static" / "index.html").exists() and (CODE_DIR / "static" / "_next").exists()
    rows.append(("Web UI built (static/)", built, "" if built else "cd frontend && npm install && npm run build"))
    node = shutil.which("npm") is not None
    if not built:
        rows.append(("Node.js / npm (to build the UI)", node, "" if node else "install Node 20+ from nodejs.org"))
    running = _server_up()
    rows.append(("Web app running on http://127.0.0.1:8500", running, "" if running else "python -m texel_paint serve"))

    for label, passed, note in rows:
        print(f"[{'ok' if passed else '--'}] {label}" + (f"  {note}" if note else ""))
    print()
    if not ok:
        print("Painting needs Python, Pillow and a writable folder. Fix the lines marked [--] above.")
        return 1
    print("You can paint now:   python -m texel_paint help-ops")
    if web_deps and built and not running:
        print("Open the web UI:     python -m texel_paint serve      (then http://127.0.0.1:8500)")
    elif running:
        print("Open http://127.0.0.1:8500 - new designs from the CLI appear there live.")
    return 0


def serve(host: str, port: int) -> int:
    """Start the Texel Studio web app (same as `python server.py`, but bound to localhost by default)."""
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1
    sys.path.insert(0, str(CODE_DIR))
    print(f"Texel Studio on http://{host}:{port}   (Ctrl+C to stop)")
    uvicorn.run("server:app", host=host, port=port, app_dir=str(CODE_DIR))
    return 0

"""
Command line interface:  python -m texel_paint <command> ...

Typical loop (one preview per pass, numbers instead of images where possible):
    python -m texel_paint new "iron sword" --size 32 --type item --colors "#1b1226,#4a5d78,#9fb4d0,#e8f2ff"
    python -m texel_paint ops 7 - <<'OPS'
    rect 4 4 27 27 #4a5d78
    bevel [rect,4,4,27,27] #9fb4d0 #1b1226
    OPS
    python -m texel_paint lint 7
Run `python -m texel_paint help-ops` for every drawing operation and `python -m texel_paint doctor` to check your setup.
"""

import argparse
import sys
from pathlib import Path

from texel_paint import __version__, batch, colors as C, doctor, guard, imaging, store
from texel_paint.lint import lint
from texel_paint.painter import apply_ops, op_reference
from texel_paint.script import parse_ops
from texel_paint.stamps import list_stamps


def _ints(text: str, count: int) -> tuple[int, ...]:
    values = [int(t) for t in text.lower().replace("x", ",").replace(" ", ",").split(",") if t != ""]
    if len(values) != count:
        raise SystemExit(f"'{text}': expected {count} numbers")
    return tuple(values)


def _palette_arg(args) -> list[str] | None:
    if getattr(args, "colors", None):
        if args.colors in ("none", "auto"):
            return []
        return [h.strip() if h.strip().startswith("#") else "#" + h.strip() for h in args.colors.split(",")]
    return None


def _show(canvas, scale=None, note="", before=None, ascii_dump=False, used=False, crop=True, region=None, quiet=False):
    """Compact output: header, change statistics, preview path. Grid/colour list only on request."""
    print(f"id={canvas.gid} size={canvas.size}" + (f" rect={canvas.width}x{canvas.height}" if canvas.is_rect else "")
          + (f" {note}" if note else ""))
    if before is not None:
        changed = [(x, y) for y in range(canvas.size) for x in range(canvas.size) if before[y][x] != canvas.pixels[y][x]]
        if changed:
            xs, ys = [p[0] for p in changed], [p[1] for p in changed]
            print(f"changed: {len(changed)} px, area x{min(xs)}-{max(xs)} y{min(ys)}-{max(ys)}")
        else:
            print("changed: 0 px")
    if not quiet:
        store.ensure_dirs()
        print("preview:", imaging.preview(canvas, str(store.WORK / f"preview_{canvas.gid}.png"), scale, crop=crop, region=region))
    if used:
        indices = sorted({v for r in canvas.pixels for v in r if v >= 0})
        print("colors:", " ".join(f"{i}={canvas.palette[i]}" for i in indices))
    if ascii_dump:
        print(imaging.dump_text(canvas, region))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="texel_paint", description="Paint pixel art from the command line or from a coding agent.")
    parser.add_argument("--version", action="version", version=f"texel_paint {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def view_flags(p):
        p.add_argument("--scale", type=int, help="pixel size of the preview")
        p.add_argument("--full", action="store_true", help="show the whole canvas, not just the content")
        p.add_argument("--region", help="x1,y1,x2,y2 only this part")
        p.add_argument("--dump", action="store_true", help="print ASCII rows (reusable with the rows op)")
        p.add_argument("--used", action="store_true", help="list the colours in use")

    sub.add_parser("doctor", help="check the setup and print next steps")
    p = sub.add_parser("serve", help="start the web app on localhost"); p.add_argument("--port", type=int, default=8500); p.add_argument("--host", default="127.0.0.1")
    sub.add_parser("help-ops", help="list every drawing operation")
    sub.add_parser("palettes", help="list the saved palettes")
    p = sub.add_parser("new", help="create a design"); p.add_argument("prompt"); p.add_argument("--size", default="16", help="32 or a rectangle like 52x72")
    p.add_argument("--type", default="block", help="block (tileable) or item (transparent)"); p.add_argument("--colors", help="#hex,#hex | none"); p.add_argument("--palette-id", type=int)
    p = sub.add_parser("ops", help="apply operations (text syntax via stdin '-' , a file, or JSON)"); p.add_argument("id", type=int); p.add_argument("json", nargs="?")
    p.add_argument("-f", "--file"); p.add_argument("--quiet", action="store_true", help="no preview image"); p.add_argument("--lint", action="store_true"); view_flags(p)
    p = sub.add_parser("view", help="preview a design"); p.add_argument("id", type=int); p.add_argument("--quiet", action="store_true"); view_flags(p)
    p = sub.add_parser("undo", help="undo the last ops call (30 steps)"); p.add_argument("id", type=int); p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("from-image", help="quantise a reference image into a design"); p.add_argument("image"); p.add_argument("--size", type=int, default=32)
    p.add_argument("--colors", help="#hex,.. fixed palette"); p.add_argument("--ncolors", type=int, default=12); p.add_argument("--palette-id", type=int)
    p.add_argument("--id", type=int, help="overwrite this design"); p.add_argument("--prompt", default="from reference image"); p.add_argument("--type", default="item"); p.add_argument("--nearest", action="store_true")
    p = sub.add_parser("palette-from-image", help="extract a palette"); p.add_argument("image"); p.add_argument("n", type=int, nargs="?", default=12)
    p = sub.add_parser("ramp", help="dark-to-light ramp for a colour (cool shadows, warm lights)"); p.add_argument("hex"); p.add_argument("n", type=int, nargs="?", default=5)
    p = sub.add_parser("dump", help="ASCII rows"); p.add_argument("id", type=int); p.add_argument("--region")
    p = sub.add_parser("refmap", help="reference image as ASCII colour map"); p.add_argument("image"); p.add_argument("--size"); p.add_argument("--ncolors", type=int, default=10); p.add_argument("--colors"); p.add_argument("--region")
    p = sub.add_parser("compare", help="numeric comparison with a reference image"); p.add_argument("id", type=int); p.add_argument("image"); p.add_argument("--ref-size"); p.add_argument("--at", default="0,0"); p.add_argument("--out")
    p = sub.add_parser("export", help="write a PNG"); p.add_argument("id", type=int); p.add_argument("--canvas", help="WxH transparent canvas"); p.add_argument("--at", default="0,0")
    p.add_argument("--scale", type=int, default=1); p.add_argument("--out"); p.add_argument("--datauri", action="store_true")
    p = sub.add_parser("lint", help="quality check as text"); p.add_argument("id", type=int)
    p = sub.add_parser("variant", help="recoloured copy: --map '#old:#new,..' or --hue/--sat/--light"); p.add_argument("id", type=int); p.add_argument("name")
    p.add_argument("--map", default=""); p.add_argument("--hue", type=float, default=0.0); p.add_argument("--sat", type=float, default=1.0); p.add_argument("--light", type=float, default=0.0); p.add_argument("--only", default="")
    p = sub.add_parser("compose", help="stack layers: --layers 'g12@10,17:sh;base.png' --canvas 52x72"); p.add_argument("--layers", required=True); p.add_argument("--canvas", default="64x64")
    p.add_argument("--out"); p.add_argument("--scale", type=int, default=1); p.add_argument("--bg")
    p = sub.add_parser("mockup", help="design on a base image at 1x/3x/8x and reduced size"); p.add_argument("design"); p.add_argument("--on", required=True); p.add_argument("--at"); p.add_argument("--fit", type=int); p.add_argument("--out")
    p = sub.add_parser("ship", help="write the PNG into your project (backs up the old file)"); p.add_argument("id", type=int); p.add_argument("target"); p.add_argument("--dry", action="store_true")
    p = sub.add_parser("batch", help="build many designs from a file with @design blocks"); p.add_argument("file"); p.add_argument("--dry", action="store_true", help="do not write ship targets")
    sub.add_parser("macros", help="list stored macros"); sub.add_parser("stamps", help="list stored stamps")
    return parser


def run(args) -> int:
    cmd = args.cmd
    region = lambda: _ints(args.region, 4) if getattr(args, "region", None) else None

    if cmd == "doctor":
        return doctor.run()
    if cmd == "serve":
        return doctor.serve(args.host, args.port)
    if cmd == "help-ops":
        width = max(len(n) for n, _ in op_reference())
        for name, doc in op_reference():
            print(doc if doc.split()[0] == name else f"{name:<{width}}  {doc}")
        print("\nCoordinates, colours and regions: see docs/PAINT_CLI.md (or the top of texel_paint/painter.py).")
    elif cmd == "palettes":
        for pid, name, cols in store.list_palettes():
            print(pid, name, len(cols), "colors:", " ".join(cols))
    elif cmd == "new":
        w, h = batch.parse_size(args.size)
        palette = _palette_arg(args)
        gid = store.create(args.prompt, max(w, h), args.type, palette, args.palette_id, width=w, height=h)
        canvas = store.load(gid)
        store.save(gid, canvas, "created")
        print(f"id={gid} size={canvas.size}" + (f" rect={w}x{h}" if canvas.is_rect else "") + " (new, empty)")
        print("palette:", " ".join(f"{i}={c}" for i, c in enumerate(canvas.palette)) or "(empty - colours are added as you paint)")
    elif cmd == "ops":
        canvas = store.load(args.id)
        raw = sys.stdin.read() if args.json == "-" else (Path(args.file).read_text(encoding="utf-8") if args.file else args.json)
        if not raw:
            raise SystemExit("No operations given (use '-' to read stdin, -f FILE, or pass them as an argument)")
        ops = parse_ops(raw)
        before = [r[:] for r in canvas.pixels]
        store.snapshot(args.id, canvas)
        errors, notes = apply_ops(canvas, ops)
        store.save(args.id, canvas, f"{len(ops)} ops")
        _show(canvas, args.scale, f"({len(ops)} ops)", before, args.dump, args.used, not args.full, region(), args.quiet)
        if notes:
            print("new colors:", " ".join(notes))
        if args.lint:
            summary, warnings = lint(canvas)
            print("lint:", summary, ("| " + "; ".join(warnings)) if warnings else "| ok")
        for error in errors:
            print("ERROR:", error)
        return 1 if errors else 0
    elif cmd == "view":
        _show(store.load(args.id), args.scale, "", None, args.dump, args.used, not args.full, region(), args.quiet)
    elif cmd == "undo":
        print("undone" if store.undo(args.id) else "nothing to undo")
        _show(store.load(args.id), quiet=args.quiet)
    elif cmd == "from-image":
        palette = _palette_arg(args)
        if palette is None and args.palette_id:
            palette = next(p[2] for p in store.list_palettes() if p[0] == args.palette_id)
        if args.id:
            canvas = store.load(args.id)
            pixels, palette = imaging.image_to_pixels(args.image, canvas.size, palette or canvas.palette, args.ncolors, not args.nearest)
            store.snapshot(args.id, canvas)
            canvas.pixels, canvas.palette = pixels, palette
            store.save(args.id, canvas, "from-image")
        else:
            pixels, palette = imaging.image_to_pixels(args.image, args.size, palette, args.ncolors, not args.nearest)
            gid = store.create(args.prompt, args.size, args.type, palette, pixels=pixels)
            canvas = store.load(gid)
            store.save(gid, canvas, "from-image")
        _show(canvas, note="(from reference image)")
    elif cmd == "palette-from-image":
        print(" ".join(C.palette_from_image(args.image, args.n)))
    elif cmd == "ramp":
        print(" ".join(C.make_ramp(args.hex, args.n)))
    elif cmd == "dump":
        print(imaging.dump_text(store.load(args.id), region()))
    elif cmd == "refmap":
        palette = [h.strip() for h in args.colors.split(",")] if args.colors else None
        print(imaging.refmap(args.image, _ints(args.size, 2) if args.size else None, args.ncolors, palette, region()))
    elif cmd == "compare":
        print(imaging.compare(store.load(args.id), args.image, _ints(args.ref_size, 2) if args.ref_size else None, _ints(args.at, 2), args.out))
    elif cmd == "export":
        print(imaging.export(store.load(args.id), _ints(args.canvas, 2) if args.canvas else None, _ints(args.at, 2), args.scale, args.out, args.datauri))
    elif cmd == "lint":
        summary, warnings = lint(store.load(args.id))
        print(summary, ("| " + "; ".join(warnings)) if warnings else "| ok")
    elif cmd == "variant":
        pairs = dict(t.split(":") for t in args.map.split(",") if ":" in t)
        new_id = batch.variant(args.id, args.name, pairs, args.hue, args.sat, args.light, [t for t in args.only.split(",") if t])
        print(f"id={new_id} ({args.name}) from {args.id}")
    elif cmd == "compose":
        w, h = batch.parse_size(args.canvas)
        image = imaging.compose([x for x in args.layers.split(";") if x], (w, h), args.bg)
        if args.scale > 1:
            image = image.resize((w * args.scale, h * args.scale), Image.NEAREST)
        out = Path(args.out) if args.out else store.WORK / "compose.png"
        store.ensure_dirs()
        image.save(out)
        print("compose:", out.resolve())
    elif cmd == "mockup":
        at = _ints(args.at, 2) if args.at else None
        sheet = imaging.zoom_sheet(imaging.mockup(imaging.load_source(args.design), imaging.load_source(args.on), at, args.fit))
        out = Path(args.out) if args.out else store.WORK / "mockup.png"
        store.ensure_dirs()
        sheet.convert("RGB").save(out)
        print("mockup:", out.resolve(), "(1x | 3x | 8x | reduced)")
    elif cmd == "ship":
        print("ship:", batch.ship(args.id, args.target, args.dry))
    elif cmd == "batch":
        lines, _ = batch.run_batch(Path(args.file).read_text(encoding="utf-8"), args.dry)
        print("\n".join(lines))
        return 1 if any(" ERROR" in l for l in lines) else 0
    elif cmd == "macros":
        from texel_paint.script import load_macros
        for name, (params, body) in sorted(load_macros().items()):
            print(f"{name} {' '.join(params)}  ({len(body)} lines)")
    elif cmd == "stamps":
        print(", ".join(list_stamps()) or "(none)")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd != "serve":      # the web server runs until you stop it, the watchdog is only for painting runs
        guard.start()
    try:
        return run(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


from PIL import Image  # noqa: E402  (used by compose --scale)

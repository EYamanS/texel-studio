# Texel Studio: instructions for coding agents (Claude Code and others)

You paint pixel art here with the `texel_paint` CLI. No API key is needed and you do **not** use the built-in LangGraph
agent (`agent.py`) or the "Generate Sprite" button. Designs are stored in the shared SQLite database and appear **live** in
the web UI (`python -m texel_paint serve`, http://127.0.0.1:8500) where the user can edit and export them.

Run everything from this folder. First time: `python -m texel_paint doctor`. All operations: `python -m texel_paint help-ops`.
Full reference: `docs/PAINT_CLI.md`.

## Be efficient: better pixels with fewer calls and tokens

1. **Serial or several designs: one batch file, one call.** Write `@design NAME size=32 ship=path.png` blocks, run
   `python -m texel_paint batch set.txt`. You get a lint line per design and ONE overview image. Re-running overwrites by name.
2. **Judge with numbers first.** `lint <id>` (or `ops ... --lint`, batch does it automatically) reports coverage, colours, stray
   pieces, single pixels, outline darkness, symmetry. Look at an image only when lint warns or the design is new.
   Use `--quiet` on intermediate `ops` calls, one preview per pass.
3. **Let the tool do the craft.** `bevel` / `rim` (light top-left, shadow bottom-right), `gradient` (dithered ramps),
   `autoline` (outline in a darker neighbour colour, once), `polish`, `scatter` (grain), shapes (`heart leaf star disc donut
   arc rrect diamond`), parts (`gem rivet sparkle dew card_frame`). Hex colours in ops are added to the palette automatically.
4. **Reuse.** `grab`/`stamp`/`corners` for repeated pieces, `macro`/`use` and `for` for families of designs,
   `variant <id> NAME --hue 200` for recoloured copies.
5. Reference image available? `refmap` / `compare` give numbers instead of repeated image viewing.

## Workflow

```bash
python -m texel_paint new "iron sword" --size 32 --type item --colors none     # prints the id; colours are added as you paint
python -m texel_paint ops <id> - --quiet --lint <<'OPS'
rect 4 12 27 18 #4a5d78
bevel [rect,4,12,27,18] #9fb4d0 #1b1226
autoline
OPS
python -m texel_paint view <id>                                                 # one preview image
python -m texel_paint export <id> --scale 8 --out sword.png                    # or: ship via a batch file
```

* Text syntax: one op per line, `//` comments, lists `[a,b]`, hex colours directly, dictionaries without quotes `{#f00:#0f0}`.
* `(0,0)` is top-left. Classic ops (`circle`, `ellipse`, `ring`) take pixel indices; shape ops (`disc`, `heart`, `star` ...) take
  pixel-edge coordinates (`36` = edge between pixels 35|36), so even widths are exactly symmetric.
* Non-square sprites: `--size 52x72` (usable rectangle, exports are cropped to it).
* Quality rules: one light source (top-left), 3-4 tones per material, shadows cooler, lights warmer, a readable silhouette at 1x,
  selective outline instead of pure black, no banding or single-pixel noise unless intended, mirror symmetric things.
* `outline` / `soutline` / `autoline` once only (a second call doubles the outline); use `undo <id>` to step back.

## Guard rails

* A watchdog aborts runs after 60 s / 1.5 GB. If it triggers, a loop in your ops is runaway: fix the ops, do not raise the limits.
* Do not delete `.env`, `pixel_studio.db`, `output/` or `paint_work/`. Never put API keys into files you create.
* `ship=` / `texel_paint ship` back up the file they overwrite (`paint_work/ship_backup/`). Use `--dry` to see paths first.
* The frontend lives in `frontend/` (Next.js, see `frontend/AGENTS.md`); `static/` is its build output and is git-ignored.

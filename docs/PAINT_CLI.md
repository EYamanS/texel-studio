# Painting with Claude Code (or any coding agent): `texel_paint`

`texel_paint` is a command-line painter that works on the **same database and output folder as the web app**.
A coding agent such as [Claude Code](https://claude.com/claude-code) calls it to paint pixel art; every design
appears **live** in the Texel Studio web UI, where you can keep editing it by hand, export it, or build tilesets.

* **No API key and no model call.** The agent *is* the painter; `texel_paint` only supplies the brushes, a compact
  text syntax, quality checks and a batch mode.
* **Only needs Pillow** (`pip install Pillow`). The web UI is optional (it is how you watch and edit).
* **Built for many designs at low token cost:** one batch file builds a whole set, quality checks come back as text,
  and you look at one overview picture instead of many large ones.

## Setup (about two minutes)

```bash
git clone https://github.com/EYamanS/texel-studio.git
cd texel-studio
pip install Pillow                # painting only
python -m texel_paint doctor      # checks everything and prints next steps
```

To also get the web UI (live view, manual editing, export):

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python -m texel_paint serve       # http://127.0.0.1:8500  (localhost only)
```

(`./start.sh` / `start.bat` do the same in one go.) Open the UI, then start your agent **in the project folder**:

```bash
claude        # Claude Code reads CLAUDE.md in this folder automatically
```

and ask for something: *"Paint a 32x32 iron sword with texel_paint and check it with lint."* The design shows up in the UI
history while it is being painted. The **Paint with an agent** panel in the UI's sidebar shows the live link and has
copy-paste commands; tick *Open designs the agent paints* to follow along on the canvas.

Other agents (Codex, Cursor, Gemini CLI ...) work the same way: they read `AGENTS.md`.

## The basics

```bash
python -m texel_paint new "iron sword" --size 32 --type item --colors "#1b1226,#4a5d78,#9fb4d0,#e8f2ff"
python -m texel_paint ops 7 - <<'OPS'          # 7 = the design id printed by `new`
rect 4 12 27 18 #4a5d78
bevel [rect,4,12,27,18] #9fb4d0 #1b1226
OPS
python -m texel_paint lint 7                   # quality check as text
python -m texel_paint view 7 --scale 12        # preview PNG with coordinate ruler
python -m texel_paint export 7 --scale 8 --out sword.png
python -m texel_paint help-ops                 # every drawing operation, one line each
```

`ops` applies operations, saves, and prints a compact result (changed pixels, new colours, preview path).
`--quiet` skips the preview image, `--lint` appends the quality check, `undo <id>` goes back (30 steps).

### Conventions

* `(0,0)` is the top-left pixel; x grows right, y grows down.
* **Colours** are palette indices *or* hex (`#rgb`, `#rrggbb`, `#rrggbbaa` for alpha). An unknown hex colour is
  appended to the palette and reported (`new colors: #12ab34=7`), so a typo never silently becomes a similar colour.
  Start with `--colors none` to build the palette while painting.
* **Rectangles:** `--size 52x72` creates a design with a 52x72 usable area (stored on a 72x72 grid). Everything outside is
  discarded, exports are cropped to the rectangle, and the web UI shows the rectangle.
* **Classic ops** (`circle`, `ellipse`, `ring` ...) take *pixel indices* as centres. **Shape ops** (`disc`, `donut`, `heart`,
  `leaf`, `star`, `diamond`, `arc`, `rrect`) take *pixel-edge* coordinates: `36` is the edge between pixels 35 and 36, `35.5`
  is the middle of pixel 35. Even widths are therefore perfectly symmetric.
* **Regions** can be used in `fillr`, `bevel`, `rim`, `gradient`, `recolor`, `pattern`, `shade`, `scatter`, `grab` ...:
  `[rect,x1,y1,x2,y2] [ellipse,cx,cy,rx,ry] [circle,cx,cy,r] [poly,[[x,y],..]] [all] [filled] [color,c1,c2]`
  `[union,r1,r2] [minus,r1,r2] [inter,r1,r2]` and every shape: `[disc,..] [donut,..] [heart,..] [star,..]` ...
* Text syntax: one op per line, `//` comments, lists as `[a,b]`, dictionaries without quotes `{#ff0000:#00ff00}`.
  JSON (`[["rect",0,0,7,7,1]]`) works too.

## Better pixels with fewer calls

| Goal | Use |
| --- | --- |
| Light and shadow on any shape | `bevel region light shadow` (explicit colours) or `rim region` (derives warmer lights / cooler shadows from the pixels' own colours) |
| Soft shading across an area | `gradient region [c1,c2,c3] angle`, `rgradient region [..]` (Bayer dithering) |
| Outline that is not plain black | `autoline` (darker, cooler version of the neighbouring colour; apply once) |
| Clean up | `polish` (1px holes, stray pixels), `despeckle`, `pline` (pixel-perfect lines) |
| Texture | `scatter region color density`, `noise`, `voronoi`, `pattern` |
| Organic shapes | `heart`, `leaf`, `star`, `disc`, `donut`, `arc`, `bezier` |
| Ready-made parts | `gem`, `rivet`, `sparkle`, `dew`, `card_frame x1 y1 x2 y2 common|rare|legendary` |
| Reuse | stamps (`grab`, `stamp`, `stampc`, `corners`), macros (`macro`/`use`), loops (`for`) |
| Check without looking | `lint <id>`: coverage, colour count, stray pieces, single pixels, outline, symmetry |

### Macros, loops and expressions

```text
macro gemstar $x $y $color
  star $x $y 7 3 5 -90 $color
  rim [star,$x,$y,7,3,5,-90]
endmacro
use gemstar 10 10 #ffd23c                    // macros are stored in paint_work/lib and survive between runs

for i 0 3                                    // inclusive
  diamond ${12+12*$i} 40 4 4 #e04040         // ${...}: + - * / % ( ) sin cos (degrees) sqrt pi min max abs round int hyp
endfor
```

### Stamps

`grab name region` remembers painted pixels (colour-independent, stored as hex in `paint_work/stamps/`).
`stamp name x y [rotation 0|90|180|270] [flip x|y|xy] [scale] [{#old:#new}]` places them anywhere, in any later design.
`corners name x1 y1 x2 y2` places a top-left corner stamp into all four corners.

## Batch mode: a whole set in one call

```text
@design iron_sword size=32 ship=assets/items/iron_sword.png
...operations...
@design card_common size=52x72 on=assets/ui/card_bg.png at=8,15 fit=36
card_frame 0 0 51 71 common
```

```bash
python -m texel_paint batch set.txt          # --dry shows the ship paths without writing
```

For each `@design` it builds the design, runs `lint`, optionally writes the PNG to `ship=` (an existing file is backed up
to `paint_work/ship_backup/`), and finally writes **one overview picture** (`paint_work/batch_sheet.png`).
Re-running a batch overwrites designs of the same name instead of piling up new ones. Script errors in one design are
reported and do not stop the others. Options: `size`, `colors`, `ship`, `on`/`at`/`fit` (show the design placed on a base
image in the overview), `lint=0`. Set `TEXEL_SHIP_ROOT` to resolve relative `ship=` paths against your game project.

More tools: `variant <id> NAME --hue 200` or `--map "#old:#new"` (recoloured copy, e.g. rarity colours), `compose
--layers "g12@10,17:sh;base.png" --canvas 52x72` (layers with opacity `*0.8` and drop shadow `:sh`), `mockup DESIGN --on
base.png` (1x / 3x / 8x and a reduced "how it reads in the HUD" view), `compare`/`refmap` (numeric comparison with a
reference image), `from-image`, `palette-from-image`, `ramp`.

## How it connects to the web app

* Shared files: `pixel_studio.db` and `output/` (set `TEXEL_HOME` to move both for the CLI *and* the server).
* The server exposes `GET /api/live` (server-sent events). The UI subscribes, refreshes the history when anything changes
  and, with *Open designs the agent paints* ticked, loads designs created by `texel_paint` onto the canvas as they are painted.
  `GET /api/agent` tells the UI how to reach the CLI from this installation.
* Designs painted by the CLI carry the model name `texel-paint` in the history.
* The CLI works without the server running (everything is stored in SQLite); start the UI whenever you want to look.
* Remote/Redis/S3 deployments are not covered by the CLI; it is a local workflow.

## Safety

`texel_paint` starts a watchdog that aborts any run after 60 s or 1.5 GB (`TEXEL_MAX_SECONDS`, `TEXEL_MAX_MB`), numbers in
ops are range-checked, expressions are restricted to arithmetic, and `ship` never overwrites without a backup.
`python -m texel_paint serve` binds to `127.0.0.1`; plain `python server.py` binds to all interfaces and has no authentication,
so do not expose it to a network you do not trust.

## Tests

```bash
python -m unittest discover -s tests -v      # standard library only, uses a throw-away data folder
```

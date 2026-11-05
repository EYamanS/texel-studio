"""
texel_paint - paint pixel art from the command line (or from any coding agent such as Claude Code).

It uses the same SQLite database and output folder as the Texel Studio web app, so everything you
paint here shows up (live) in the web UI history, where you can keep editing, export and generate tilesets.

No API key and no AI model call is needed: the *calling agent* is the painter, this package only provides
the drawing tools, a compact text syntax for them, quality checks and a batch mode.

Quick start:  python -m texel_paint doctor
Reference:    python -m texel_paint help-ops      (all drawing operations)
Docs:         docs/PAINT_CLI.md
"""

__version__ = "1.0.0"

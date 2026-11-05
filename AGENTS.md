# Instructions for coding agents

This repository can be driven by any coding agent (Claude Code, Codex, Cursor, Gemini CLI ...) through the `texel_paint`
command-line painter. The complete, agent-oriented instructions are in [`CLAUDE.md`](CLAUDE.md), and the reference is in
[`docs/PAINT_CLI.md`](docs/PAINT_CLI.md).

Short version:

```bash
python -m texel_paint doctor        # check the setup once
python -m texel_paint help-ops      # every drawing operation
python -m texel_paint batch set.txt # build many designs in one call, lint them, get one overview image
```

No API key is needed: you are the painter. Designs appear live in the web UI (`python -m texel_paint serve`).

# Pixel Studio

**The only pixel art tool that actually paints like a real artist.**

Every other AI pixel art generator is a diffusion model pretending to understand pixels. They output blurry approximations — inconsistent colors, broken edges, half-pixel artifacts, and results that look different every time you run the same prompt. They don't understand what a pixel *is*.

Pixel Studio is different. An AI agent picks up a brush, places pixels on a canvas one at a time, steps back to look at what it drew, and decides what to fix. It uses shapes, noise fills, and detail tools — the same way a human pixel artist works. Every pixel is intentional. Every color is from your palette. The output is exact, consistent, and game-ready.

Built with LangGraph + Gemini/OpenAI. Runs locally with a web UI.

https://github.com/user-attachments/assets/bc2c0e85-062a-4f5e-ac7c-b8c0d91fe63d


## How it works

1. **Describe** what you want ("a mossy cobblestone block")
2. **Generate concept art** — AI creates a reference image for guidance
3. **Confirm** the reference (or revise with feedback)
4. **Watch the agent paint** — it uses drawing tools to build the sprite step by step
5. **Chat to edit** — tell the agent "make the top darker" and it continues painting
6. **Export** — native size PNG, upscaled 512px, or full autotile tileset (16 variants)

## Why not diffusion?

| | Diffusion generators | **Pixel Studio** |
|---|---|---|
| Output | Blurry approximation scaled down | **Exact palette-indexed pixels** |
| Colors | Random, needs post-processing | **Your palette, every time** |
| Consistency | Different result every run | **Deterministic tool calls** |
| Edges | Anti-aliased, half-pixels | **Clean, game-ready edges** |
| Control | Prompt and pray | **Chat to refine, pixel by pixel** |
| Process | Black box | **Watch it paint, step by step** |
| Tileable | Almost never | **Built-in autotile generation** |

Diffusion models hallucinate pixels. This tool places them.

## Agent Tools

**Drawing**
- `draw_pixel`, `draw_pixels` — individual pixels
- `fill_rect`, `fill_row`, `fill_column` — rectangular fills
- `draw_line` — Bresenham lines
- `draw_circle`, `draw_ellipse` — round shapes (filled or outline)
- `draw_triangle` — filled triangles

**Texture**
- `noise_fill_rect`, `noise_fill_circle` — random color distribution for natural variation
- `voronoi_fill` — cell/stone patterns (cobblestone, rocks, organic surfaces)

**Inspection**
- `view_canvas` — see current pixel grid + color usage
- `get_pixel` — check a single pixel value

## Features

- **Sprite types** — Block (tileable) and Item Icon (transparent bg) with type-specific prompts
- **Multi-provider** — Gemini (API key or Vertex AI) and OpenAI models
- **Concept art reference** — AI generates a reference image before pixel painting
- **Live streaming** — watch the sprite build in real-time via SSE
- **Chat continuation** — send follow-up edits to the same agent session
- **Manual pixel editing** — click to paint, right-click to erase
- **Palette management** — create, edit, and reuse color palettes
- **Autotile generation** — generate all 16 edge variants for tilemap use
- **Export** — native PNG, upscaled preview, or full tileset folder
- **History** — browse and reload past generations
- **LangSmith tracing** — optional observability for agent runs

## Setup

```bash
git clone https://github.com/EYamanS/pixel-studio.git
cd pixel-studio

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your API key(s)

python server.py
```

Open `http://localhost:8500`

## Authentication

You need at least one AI provider configured:

**Gemini** (for both concept art + agent painting)
- Get a free API key at [aistudio.google.com](https://aistudio.google.com/apikey)
- Add `GEMINI_API_KEY=your_key` to `.env`
- Or use a Google Cloud service account for Vertex AI

**OpenAI** (agent painting only, concept art still uses Gemini)
- Add `OPENAI_API_KEY=your_key` to `.env`

Both can be configured simultaneously — choose the model per generation in the UI.

## Autotile Export

After generating a block sprite, click "Generate Tileset" to create all 16 autotile variants:
- Edge darkening on exposed sides
- Outline on exposed edges
- Rounded corners where two exposed edges meet

Output: `BlockName_00.png` through `BlockName_15.png`

## Tech Stack

- **Backend**: Python, FastAPI, LangGraph, LangChain
- **AI**: Google Gemini + OpenAI (pluggable)
- **Frontend**: Vanilla HTML/CSS/JS (single file, no build step)
- **Tracing**: LangSmith (optional)

## License

Custom license — free for personal and non-commercial use with attribution required. Commercial use needs permission. See [LICENSE](LICENSE).

---

Built by [Emir Yaman Sivrikaya](https://github.com/EYamanS)

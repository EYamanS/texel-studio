# Texel Studio

**The only pixel art tool that actually paints like a real artist.**

Every other AI pixel art generator is a diffusion model pretending to understand pixels. They output blurry approximations — inconsistent colors, broken edges, half-pixel artifacts, and results that look different every time you run the same prompt. They don't understand what a pixel *is*.

Texel Studio is different. An AI agent picks up a brush, places pixels on a canvas one at a time, steps back to look at what it drew, and decides what to fix. It uses shapes, noise fills, and detail tools — the same way a human pixel artist works. Every pixel is intentional. Every color is from your palette. The output is exact, consistent, and game-ready.

This is the open-source engine that powers [texel.studio](https://texel.studio).

https://github.com/user-attachments/assets/bc2c0e85-062a-4f5e-ac7c-b8c0d91fe63d

## How it works

1. **Describe** what you want ("a mossy cobblestone block")
2. **Generate concept art** — AI creates a reference image for guidance
3. **Confirm** the reference (or revise with feedback)
4. **Watch the agent paint** — it uses drawing tools to build the sprite step by step
5. **Chat to edit** — tell the agent "make the top darker" and it continues painting
6. **Export** — native size PNG, upscaled 512px, or full autotile tileset (16 variants)

## Why not diffusion?

| | Diffusion generators | **Texel Studio** |
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
- `draw_rotated_rect` — angled rectangles

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
- **S3 storage** — optional S3-compatible object storage for shared file access across workers
- **Observability** — optional LangSmith and/or PostHog LLM analytics tracing

## Setup

```bash
git clone https://github.com/EYamanS/texel-studio.git
cd texel-studio

# Quick start (handles everything)
./start.sh

# Or set up manually:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # edit with your API key(s)
cd frontend && npm install && npm run build && cd ..
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

## Scaling (Optional)

For concurrent generation support, add Redis and run workers:

```bash
# Set in .env
REDIS_URL=redis://localhost:6379

# Run the API server + worker(s)
python server.py &
python worker.py &
python worker.py &  # add more workers for more parallelism
```

Workers pull jobs from a Redis queue and publish results via pub/sub. Chat continuation is automatically routed to the worker that holds the agent session.

Without Redis, the engine handles one generation at a time — fine for personal use.

## Storage (Optional)

By default, generated images and references are saved to the local filesystem. For multi-worker deployments where workers run on separate machines, configure S3-compatible object storage:

```bash
# Set in .env — works with AWS S3, Railway Object Store, Cloudflare R2, MinIO, etc.
ENDPOINT=https://your-s3-endpoint
ACCESS_KEY_ID=your_key
SECRET_ACCESS_KEY=your_secret
BUCKET=your_bucket
```

Without these, everything uses the local filesystem.

## Observability (Optional)

**LangSmith** — LangChain's tracing platform:
```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your_key
LANGSMITH_PROJECT=texel-studio
```

**PostHog LLM Analytics** — traces, token counts, latency, costs:
```bash
POSTHOG_API_KEY=phc_your_key
POSTHOG_HOST=https://us.i.posthog.com
```

Both can run in parallel. Neither is required.

## Cloud Version — [texel.studio](https://texel.studio)

Don't want to self-host? The cloud version is ready to use:

- **Sign up and start creating** — no API keys, no setup, no Python
- **5 free credits daily** — no credit card required
- **Pro plan** — $9/month for 200 credits with rollover
- **Credit packs** — buy 100, 250, or 700 credits anytime
- **Per-user palettes** — create, edit, share to a public gallery
- **Generation history** — saved to your account, pick up where you left off
- **Shared gallery** — browse and copy other users' sprites and palettes

The cloud runs this same engine on Railway with Redis workers, Supabase for auth and data, and Polar.sh for billing. The generation quality is identical — the cloud just removes the friction.

**[Start creating at texel.studio →](https://texel.studio)**

## Tech Stack

- **Backend**: Python, FastAPI, LangGraph, LangChain
- **AI**: Google Gemini + OpenAI (pluggable)
- **Frontend**: Next.js (static export to `static/`)
- **Queue**: Redis (optional, for concurrent generations)
- **Storage**: S3-compatible (optional, for multi-worker file sharing)
- **Tracing**: LangSmith + PostHog (optional)

## License

Custom license — free for personal and non-commercial use with attribution required. Commercial use needs permission. See [LICENSE](LICENSE).

---

Built by [Emir Yaman Sivrikaya](https://github.com/EYamanS)

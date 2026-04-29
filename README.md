# Texel Studio

**The only pixel art tool that actually paints like a real artist.**

Every other AI pixel art generator is a diffusion model pretending to understand pixels. They output blurry approximations — inconsistent colors, broken edges, half-pixel artifacts, and results that look different every time you run the same prompt. They don't understand what a pixel *is*.

Texel Studio is different. An AI agent picks up a brush, places pixels on a canvas one at a time, steps back to look at what it drew, and decides what to fix. It uses shapes, noise fills, and detail tools — the same way a human pixel artist works. Every pixel is intentional. Every color is from your palette. The output is exact, consistent, and game-ready.

This is the open-source engine that powers [texel.studio](https://texel.studio).

https://github.com/user-attachments/assets/63e2fdde-3f15-4ffd-8b27-60acaef9a9c5


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
- **Multi-provider** — Gemini, OpenAI, and local Ollama models (100% free with Ollama)
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

**Ollama (free, runs locally)**
- Install [Ollama](https://ollama.com) and pull a model:
  ```bash
  ollama pull ggml-org/gemma-4-E4B-it-GGUF:Q8_0
  ```
- Add to `.env`:
  ```bash
  OLLAMA_MODELS=ggml-org/gemma-4-E4B-it-GGUF:Q8_0
  # OLLAMA_URL=http://localhost:11434   # default, only set if different
  ```
- That's it — no API keys, no accounts, no cost. The model runs on your machine.
- You can list multiple models: `OLLAMA_MODELS=gemma-4:8b,llama3.1:8b,qwen3:8b`
- Recommended models for pixel art: `ggml-org/gemma-4-E4B-it-GGUF:Q8_0`, `qwen3:8b`, `llama3.1:8b`

**Gemini** (for both concept art + agent painting)
- Get a free API key at [aistudio.google.com](https://aistudio.google.com/apikey)
- Add `GEMINI_API_KEY=your_key` to `.env`
- Or use a Google Cloud service account for Vertex AI

**OpenAI** (agent painting only, concept art still uses Gemini)
- Add `OPENAI_API_KEY=your_key` to `.env`

**OpenAI-compatible servers** (Llama.cpp, VLLM, LM Studio, OpenRouter, etc.)
- Point at any OpenAI-compatible endpoint and register the model names you want in the UI:
  ```bash
  OPENAI_BASE_URL=http://localhost:8080/v1
  OPENAI_MODELS=llama-3.1-8b-instruct,qwen2.5-coder-7b
  # OPENAI_API_KEY=optional_for_local_servers   # required for hosted ones like OpenRouter
  ```
- Models listed in `OPENAI_MODELS` appear in the model dropdown alongside the built-in OpenAI models.

All providers can be configured simultaneously — choose the model per generation in the UI.

> **Want to run 100% free?** Install Ollama, pull a model, set `OLLAMA_MODELS` in `.env`, and you're done. No API keys needed. Concept art generation requires Gemini, but you can skip it and paint directly.

## Autotile Export

After generating a block sprite, click "Generate Tileset" to create all 16 autotile variants:
- Edge darkening on exposed sides
- Outline on exposed edges
- Rounded corners where two exposed edges meet

Output: `BlockName_00.png` through `BlockName_15.png`

## Scaling (Optional)

For concurrent generation support, add Redis and run workers:

```bash
# Set in .env — must be Redis Stack (RediSearch module enabled),
# not vanilla Redis. The LangGraph checkpointer needs FT.* commands.
REDIS_URL=redis://localhost:6379

# Local dev: run Redis Stack via Docker
docker run -d --name texel-redis -p 6379:6379 redis/redis-stack-server:latest

# Run the API server + worker(s)
python server.py &
python worker.py &
python worker.py &  # add more workers for more parallelism
```

Workers pull jobs from a Redis queue, publish progress via pub/sub, and persist LangGraph thread state via `RedisSaver`. Any worker can resume any chat — no per-worker affinity. Vanilla Redis won't work because the checkpointer requires the search module; use Redis Stack, Redis Cloud, or a self-hosted Redis with `redisearch` enabled.

Without `REDIS_URL`, the engine runs single-process with an in-memory `MemorySaver` checkpointer — fine for personal use.

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

## Extending — adding a new job kind

The engine has a generic `Job` abstraction. Every operation the agent does
(generate, chat, reference, tileset, photo→pixel) is registered against a
`kind` string. Adding a new kind is one file:

```python
# jobs/my_thing.py
from pydantic import BaseModel
from . import JobHandler, JobContext, register_job, log, result

class MyParams(BaseModel):
    prompt: str
    size: int = 16

@register_job("my.thing")
class MyHandler(JobHandler):
    Params = MyParams

    def run(self, params: MyParams, ctx: JobContext):
        yield log("Doing the thing...")
        # ... do work, optionally yield progress(...) events ...
        yield result(status="completed", payload={"hello": "world"})
```

Then import it once at startup (e.g. add `from . import my_thing` to
`jobs/__init__.py:_load_builtins`). The dispatcher picks it up automatically.

Drive it from anywhere:

```bash
curl -N -X POST http://localhost:8500/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"kind":"my.thing","params":{"prompt":"hi","size":32}}'
```

The same endpoint works in self-hosted (in-process) and queued (Redis) modes.
Built-in kinds:

| Kind | What it does |
|---|---|
| `sprite.generate` | AI-paints a sprite from a prompt |
| `sprite.chat` | Continues editing an existing sprite via chat |
| `sprite.reference` | Generates concept art (Gemini image gen) |
| `sprite.tileset` | Builds the 16-variant autotile from a base sprite |
| `sprite.from_photo` | Quantizes a photo to the chosen palette |

`GET /api/jobs/kinds` returns the list at runtime.

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
- **AI**: Google Gemini + OpenAI + Ollama (pluggable, run free with local models)
- **Frontend**: Next.js (static export to `static/`)
- **Queue**: Redis (optional, for concurrent generations)
- **Storage**: S3-compatible (optional, for multi-worker file sharing)
- **Tracing**: LangSmith + PostHog (optional)

## License

Source-available. Use it freely — self-host, modify, use commercially, sell anything you generate. The only restriction: don't host it as a competing SaaS. See [LICENSE](LICENSE).

---

Built by [Emir Yaman Sivrikaya](https://github.com/EYamanS)

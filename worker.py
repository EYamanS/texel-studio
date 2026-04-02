#!/usr/bin/env python3
"""
Texel Studio Worker — Consumes jobs from Redis queue, runs agent/reference generation,
publishes SSE events back via Redis pub/sub.

Usage:
    python worker.py

Requires REDIS_URL environment variable.
"""

import os
import sys
import json
import time
import uuid
import base64
import signal
import sqlite3
import threading
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
load_dotenv(Path(__file__).parent.parent / "sprite-forge" / ".env")

import redis

# Import engine internals
from server import (
    get_db, gemini, sse_event, load_reference_b64,
    upscale_image, pixels_to_image,
    SPRITE_TYPES, DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT,
    DEFAULT_IMAGE_MODEL, IMAGE_GEN_MODELS,
    OUTPUT_DIR, REFS_DIR, GEMINI_MODELS,
)
from agent import run_agent_stream as agent_run, cleanup_session
from google import genai

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"

r = redis.from_url(REDIS_URL, decode_responses=True)
r_binary = redis.from_url(REDIS_URL)  # For pub/sub raw bytes

running = True

def handle_signal(sig, frame):
    global running
    print(f"[{WORKER_ID}] Shutting down...")
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def publish_event(job_id: str, event: str):
    """Publish an SSE event string to the job's pub/sub channel."""
    r.publish(f"texel:events:{job_id}", event)


def handle_generate(job: dict):
    """Run sprite generation and publish events."""
    job_id = job["job_id"]
    gen_id = job["gen_id"]
    message = job["message"]
    colors = job.get("colors", ["#c8a44e"])
    is_continuation = job.get("is_continuation", False)

    db = get_db()
    gen = db.execute("SELECT * FROM generations WHERE id = ?", (gen_id,)).fetchone()
    if not gen:
        publish_event(job_id, sse_event("error", {"message": "Generation not found"}))
        publish_event(job_id, "__done__")
        return

    palette = colors
    size = gen["size"]
    model = gen["model"] or DEFAULT_MODEL
    sprite_type = gen["sprite_type"] or "block"
    type_config = SPRITE_TYPES.get(sprite_type, SPRITE_TYPES["block"])
    system_prompt = gen["system_prompt"] or DEFAULT_SYSTEM_PROMPT
    ref_b64 = load_reference_b64(gen["reference_id"]) if not is_continuation else None

    if not is_continuation:
        db.execute("INSERT INTO generation_logs (generation_id, step, message) VALUES (?, ?, ?)",
                   (gen_id, "start", f"Agent mode: {size}x{size} with {model}"))
        db.execute("UPDATE generations SET status = 'generating' WHERE id = ?", (gen_id,))
        db.commit()
        publish_event(job_id, sse_event("log", {"step": "start", "message": f"Agent painting {size}x{size} with {model}..."}))
    else:
        db.execute("INSERT INTO generation_logs (generation_id, step, message) VALUES (?, ?, ?)",
                   (gen_id, "chat", f"Edit request: {message[:100]}"))
        db.commit()
        publish_event(job_id, sse_event("log", {"step": "chat", "message": f"Editing: {message[:100]}..."}))

    existing_pixels = None
    if is_continuation and gen["pixel_data"]:
        existing_pixels = json.loads(gen["pixel_data"])

    step_count = [0]
    last_pixel_step = [0]

    def on_step(canvas, step_type, msg):
        step_count[0] += 1
        publish_event(job_id, sse_event("log", {"step": f"{step_type}_{step_count[0]}", "message": msg}))

        is_view = "view_canvas" in msg
        if step_type == "tool_call" and (is_view or step_count[0] - last_pixel_step[0] >= 2):
            last_pixel_step[0] = step_count[0]
            px_copy = [row[:] for row in canvas.pixels]
            publish_event(job_id, sse_event("pixels", {
                "pixel_data": px_copy, "iteration": step_count[0],
                "notes": f"Step {step_count[0]}", "gen_id": gen_id,
            }))

    try:
        canvas = agent_run(
            gen_id=gen_id,
            message=message,
            palette=palette,
            size=size,
            model_name=model,
            style_prompt=system_prompt,
            sprite_type=sprite_type,
            reference_b64=ref_b64,
            on_step=on_step,
            existing_pixels=existing_pixels,
        )

        pixel_data = [row[:] for row in canvas.pixels]
        publish_event(job_id, sse_event("pixels", {
            "pixel_data": pixel_data, "iteration": step_count[0],
            "notes": "Agent finished", "gen_id": gen_id,
        }))

        db2 = get_db()
        db2.execute("UPDATE generations SET pixel_data = ?, iterations = ? WHERE id = ?",
                   (json.dumps(pixel_data), step_count[0], gen_id))

        final_img = canvas.to_image()
        filename = f"gen_{gen_id}_{size}x{size}.png"
        final_img.save(OUTPUT_DIR / filename)
        upscale_image(final_img, 512).save(OUTPUT_DIR / f"gen_{gen_id}_preview.png")

        db2.execute("UPDATE generations SET status = 'complete', image_path = ? WHERE id = ?",
                   (filename, gen_id))
        db2.commit()
        db2.close()

        publish_event(job_id, sse_event("log", {"step": "complete", "message": f"Done in {step_count[0]} steps"}))
        publish_event(job_id, sse_event("complete", {"id": gen_id, "image_path": filename}))

        # Register this worker as owner of the session (for chat routing)
        r.set(f"texel:sessions:{gen_id}", WORKER_ID, ex=3600)

    except Exception as e:
        db2 = get_db()
        db2.execute("UPDATE generations SET status = 'error' WHERE id = ?", (gen_id,))
        db2.execute("INSERT INTO generation_logs (generation_id, step, message) VALUES (?, ?, ?)",
                   (gen_id, "error", str(e)))
        db2.commit()
        db2.close()
        publish_event(job_id, sse_event("error", {"message": str(e)}))
    finally:
        publish_event(job_id, "__done__")
        db.close()


def handle_reference(job: dict):
    """Generate concept art and publish result."""
    job_id = job["job_id"]
    prompt = job["prompt"]
    feedback = job.get("feedback")
    model = job.get("model", DEFAULT_IMAGE_MODEL)
    sprite_type = job.get("sprite_type", "block")

    try:
        type_config = SPRITE_TYPES.get(sprite_type, SPRITE_TYPES["block"])
        ref_prompt = f"{prompt}\n\n{type_config['ref_prompt']}"
        if feedback:
            ref_prompt += f"\n\nRevision feedback: {feedback}"

        img_model = model if model in IMAGE_GEN_MODELS else DEFAULT_IMAGE_MODEL

        try:
            response = gemini().models.generate_content(
                model=img_model,
                contents=[ref_prompt],
                config=genai.types.GenerateContentConfig(
                    response_modalities=["Image", "Text"],
                ),
            )
        except Exception:
            response = gemini().models.generate_content(
                model=img_model,
                contents=[ref_prompt],
            )

        # Extract image from response
        ref_id = None
        for part in response.parts:
            if part.inline_data is not None:
                ref_id = f"ref_{int(time.time())}_{hash(prompt) & 0xFFFF:04x}.png"
                try:
                    img = part.as_image()
                    img.save(REFS_DIR / ref_id)
                except Exception:
                    img_bytes = part.inline_data.data
                    if isinstance(img_bytes, str):
                        img_bytes = base64.b64decode(img_bytes)
                    with open(REFS_DIR / ref_id, "wb") as f:
                        f.write(img_bytes)
                break

        if not ref_id and hasattr(response, 'candidates') and response.candidates:
            for candidate in response.candidates:
                if hasattr(candidate, 'content') and candidate.content:
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            ref_id = f"ref_{int(time.time())}_{hash(prompt) & 0xFFFF:04x}.png"
                            img_bytes = part.inline_data.data
                            if isinstance(img_bytes, str):
                                img_bytes = base64.b64decode(img_bytes)
                            with open(REFS_DIR / ref_id, "wb") as f:
                                f.write(img_bytes)
                            break

        if ref_id:
            r.publish(f"texel:result:{job_id}", json.dumps({"reference_id": ref_id}))
        else:
            r.publish(f"texel:result:{job_id}", json.dumps({"error": "No image in response"}))

    except Exception as e:
        r.publish(f"texel:result:{job_id}", json.dumps({"error": str(e)}))


def main_loop():
    """Main worker loop — pull jobs from Redis queues."""
    print(f"[{WORKER_ID}] Worker started, listening for jobs...")

    while running:
        try:
            # Listen on global queue + own queue (for chat routing)
            result = r.brpop(
                [f"texel:jobs:{WORKER_ID}", "texel:jobs"],
                timeout=5,
            )
            if result is None:
                continue

            queue_name, job_data = result
            job = json.loads(job_data)
            job_type = job.get("type", "generate")

            print(f"[{WORKER_ID}] Processing {job_type} job: {job.get('job_id', '?')}")

            if job_type == "generate":
                handle_generate(job)
            elif job_type == "chat":
                handle_generate(job)  # Same handler, is_continuation=True is in the job
            elif job_type == "reference":
                handle_reference(job)
            else:
                print(f"[{WORKER_ID}] Unknown job type: {job_type}")

        except redis.ConnectionError:
            print(f"[{WORKER_ID}] Redis connection lost, retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"[{WORKER_ID}] Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

    print(f"[{WORKER_ID}] Worker stopped.")


if __name__ == "__main__":
    main_loop()

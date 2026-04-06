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
import io
import json
import time
import uuid
import base64
import signal
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
load_dotenv(Path(__file__).parent.parent / "sprite-forge" / ".env")

import redis

from server import (
    sse_event, load_reference_b64, upscale_image, pixels_to_image,
    SPRITE_TYPES, DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT,
    DEFAULT_IMAGE_MODEL, IMAGE_GEN_MODELS,
    gemini,
)
import storage
from agent import run_agent_stream as agent_run
from google import genai

# Initialize Gemini credentials (sets GOOGLE_APPLICATION_CREDENTIALS if using service account)
try:
    gemini()
except Exception:
    pass  # Will fail later with a clear error if no credentials

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CLOUD_WEBHOOK_URL = os.getenv("CLOUD_WEBHOOK_URL")
CLOUD_API_KEY = os.getenv("API_KEY", "")
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"

r = redis.from_url(REDIS_URL, decode_responses=True)

running = True

def handle_signal(sig, frame):
    global running
    print(f"[{WORKER_ID}] Shutting down...")
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def publish_event(job_id: str, event: str):
    r.publish(f"texel:events:{job_id}", event)


def handle_generate(job: dict):
    """Run sprite generation from job payload. No SQLite dependency."""
    job_id = job["job_id"]
    gen_id = job["gen_id"]
    message = job["message"]
    colors = job.get("colors", ["#c8a44e"])
    size = job.get("size", 16)
    model = job.get("model", DEFAULT_MODEL)
    sprite_type = job.get("sprite_type", "block")
    system_prompt = job.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    reference_id = job.get("reference_id")
    is_continuation = job.get("is_continuation", False)
    existing_pixels = job.get("pixel_data")

    type_config = SPRITE_TYPES.get(sprite_type, SPRITE_TYPES["block"])
    ref_b64 = load_reference_b64(reference_id) if reference_id and not is_continuation else None

    if not is_continuation:
        publish_event(job_id, sse_event("log", {"step": "start", "message": f"Agent painting {size}x{size} with {model}..."}))
    else:
        publish_event(job_id, sse_event("log", {"step": "chat", "message": f"Editing: {message[:100]}..."}))

    step_count = [0]
    last_pixel_step = [0]

    def on_step(canvas, step_type, msg):
        step_count[0] += 1
        publish_event(job_id, sse_event("log", {"step": f"{step_type}_{step_count[0]}", "message": msg}))

        # Send pixel snapshots on tool_result (AFTER execution, canvas is updated)
        if step_type == "tool_result" and (step_count[0] - last_pixel_step[0] >= 1):
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
            palette=colors,
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

        # Save image via storage (S3 or local filesystem)
        final_img = canvas.to_image()
        filename = f"gen_{gen_id}_{size}x{size}.png"
        storage.save_image(final_img, f"output/{filename}")
        storage.save_image(upscale_image(final_img, 512), f"output/gen_{gen_id}_preview.png")

        publish_event(job_id, sse_event("log", {"step": "complete", "message": f"Done in {step_count[0]} steps"}))
        publish_event(job_id, sse_event("complete", {
            "id": gen_id, "image_path": filename, "iterations": step_count[0],
        }))

        # Register this worker as owner of the session (for chat routing)
        r.set(f"texel:sessions:{gen_id}", WORKER_ID, ex=3600)

        # Notify cloud webhook (persists result to Supabase regardless of client connection)
        external_id = job.get("external_id")
        if CLOUD_WEBHOOK_URL and external_id:
            try:
                import urllib.request
                req = urllib.request.Request(
                    CLOUD_WEBHOOK_URL,
                    data=json.dumps({
                        "external_id": external_id,
                        "pixel_data": pixel_data,
                        "image_path": filename,
                        "iterations": step_count[0],
                        "status": "completed",
                    }).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": CLOUD_API_KEY,
                    },
                )
                urllib.request.urlopen(req, timeout=30)
                print(f"[{WORKER_ID}] Webhook OK for {external_id}")
            except Exception as we:
                print(f"[{WORKER_ID}] Webhook failed for {external_id}: {we}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        publish_event(job_id, sse_event("error", {"message": str(e)}))

        # Notify cloud webhook of error too
        external_id = job.get("external_id")
        if CLOUD_WEBHOOK_URL and external_id:
            try:
                import urllib.request
                req = urllib.request.Request(
                    CLOUD_WEBHOOK_URL,
                    data=json.dumps({
                        "external_id": external_id,
                        "status": "error",
                        "error_message": str(e),
                    }).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": CLOUD_API_KEY,
                    },
                )
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                pass
    finally:
        publish_event(job_id, "__done__")


def handle_reference(job: dict):
    """Generate concept art. No SQLite dependency."""
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

        def _save_ref_part(part):
            rid = f"ref_{int(time.time())}_{hash(prompt) & 0xFFFF:04x}.png"
            try:
                buf = io.BytesIO()
                part.as_image().save(buf, format="PNG")
                storage.save_file(f"references/{rid}", buf.getvalue())
            except Exception:
                img_bytes = part.inline_data.data
                if isinstance(img_bytes, str):
                    img_bytes = base64.b64decode(img_bytes)
                storage.save_file(f"references/{rid}", img_bytes)
            return rid

        ref_id = None
        for part in response.parts:
            if part.inline_data is not None:
                ref_id = _save_ref_part(part)
                break

        if not ref_id and hasattr(response, 'candidates') and response.candidates:
            for candidate in response.candidates:
                if hasattr(candidate, 'content') and candidate.content:
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            ref_id = _save_ref_part(part)
                            break

        if ref_id:
            r.publish(f"texel:result:{job_id}", json.dumps({"reference_id": ref_id}))
        else:
            r.publish(f"texel:result:{job_id}", json.dumps({"error": "No image in response"}))

    except Exception as e:
        import traceback
        traceback.print_exc()
        r.publish(f"texel:result:{job_id}", json.dumps({"error": str(e)}))


def main_loop():
    print(f"[{WORKER_ID}] Worker started, listening for jobs...")

    while running:
        try:
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

            if job_type in ("generate", "chat"):
                handle_generate(job)
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

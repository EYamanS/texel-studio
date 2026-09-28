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
import logging
import time
import uuid
import signal
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
load_dotenv(Path(__file__).parent.parent / "sprite-forge" / ".env")

from logging_setup import setup_logging
setup_logging()
logger = logging.getLogger("texel.worker")

import redis

from server import (
    sse_event, load_reference_b64, upscale_image, pixels_to_image,
    SPRITE_TYPES, DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT,
    create_reference,
    gemini, log_startup_summary,
)
import storage
from agent import run_agent_stream as agent_run

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
    logger.info("[%s] Shutting down...", WORKER_ID)
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
                logger.info("[%s] Webhook OK for %s", WORKER_ID, external_id)
            except Exception as we:
                logger.warning("[%s] Webhook failed for %s: %s", WORKER_ID, external_id, we)

    except Exception as e:
        logger.exception("[%s] Generation %s failed", WORKER_ID, gen_id)
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

    try:
        ref_id = create_reference(
            job["prompt"],
            feedback=job.get("feedback"),
            model=job.get("model"),
            sprite_type=job.get("sprite_type", "block"),
        )
        r.publish(f"texel:result:{job_id}", json.dumps({"reference_id": ref_id}))

    except Exception as e:
        logger.error("[%s] Reference job %s failed: %s", WORKER_ID, job_id, e)
        r.publish(f"texel:result:{job_id}", json.dumps({"error": str(e)}))


def handle_generic_job(job: dict):
    """Dispatch a `{type:"job", kind, params, ...}` payload to the registered handler.

    Streams handler events as SSE bytes on `texel:events:{job_id}` so the
    server-side `/api/jobs` route (or `/api/jobs/{id}/stream`) fans them out.
    On terminal events (`result` or `error`) we POST the cloud webhook so
    the SaaS persists the result regardless of whether the user's SSE pipe
    is still attached.
    """
    from jobs import JobContext, get_handler, parse_params
    from jobs.dispatcher import event_to_sse, is_canceled

    job_id = job["job_id"]
    kind = job["kind"]
    external_id = job.get("external_id")
    raw_params = job.get("params", {})

    # Cancel-check uses the same Redis key the dispatcher writes.
    cancel_check = lambda: is_canceled(job_id)
    ctx = JobContext(job_id=job_id, external_id=external_id, cancel_check=cancel_check)

    terminal: dict | None = None
    try:
        params = parse_params(kind, raw_params)
        handler_cls = get_handler(kind)
        handler = handler_cls()

        # Initial "job" event so clients know the job started.
        publish_event(job_id, event_to_sse(_event("job", {"id": job_id, "kind": kind})))

        for ev in handler.run(params, ctx):
            publish_event(job_id, event_to_sse(ev))
            if ev.name == "result":
                terminal = {"status": "completed", **ev.data}
            elif ev.name == "error":
                terminal = {"status": "error", "error_message": ev.data.get("message", "unknown error")}
            elif ev.name == "canceled":
                terminal = {"status": "canceled"}

        if terminal is None:
            # Handler exited without emitting a terminal event — treat as error.
            terminal = {"status": "error", "error_message": "Handler exited without result"}

    except Exception as e:
        logger.exception("[%s] Job %s (%s) failed", WORKER_ID, job_id, kind)
        publish_event(job_id, event_to_sse(_event("error", {"message": str(e)})))
        terminal = {"status": "error", "error_message": str(e)}

    finally:
        publish_event(job_id, "__done__")

    # Notify cloud — the SaaS uses this to persist final state regardless of
    # whether the user's SSE connection is still alive.
    if external_id and CLOUD_WEBHOOK_URL:
        try:
            import urllib.request
            payload = {"external_id": external_id, "kind": kind, **(terminal or {})}
            req = urllib.request.Request(
                CLOUD_WEBHOOK_URL,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": CLOUD_API_KEY,
                },
            )
            urllib.request.urlopen(req, timeout=30)
            logger.info("[%s] Webhook OK for %s (%s)", WORKER_ID, external_id, kind)
        except Exception as we:
            logger.warning("[%s] Webhook failed for %s: %s", WORKER_ID, external_id, we)


def _event(name: str, data: dict):
    """Tiny wrapper so we don't import jobs.Event in worker.py top-level."""
    from jobs import Event
    return Event(name=name, data=data)


def main_loop():
    log_startup_summary()
    logger.info("[%s] Worker started, listening for jobs...", WORKER_ID)

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

            logger.info("[%s] Processing %s job: %s", WORKER_ID, job_type, job.get("job_id", "?"))

            if job_type == "job":
                # New generic shape: {type: "job", kind, job_id, external_id, params}
                handle_generic_job(job)
            elif job_type in ("generate", "chat"):
                handle_generate(job)
            elif job_type == "reference":
                handle_reference(job)
            else:
                logger.warning("[%s] Unknown job type: %s", WORKER_ID, job_type)

        except redis.ConnectionError:
            logger.warning("[%s] Redis connection lost, retrying in 5s...", WORKER_ID)
            time.sleep(5)
        except Exception as e:
            logger.exception("[%s] Error: %s", WORKER_ID, e)
            time.sleep(1)

    logger.info("[%s] Worker stopped.", WORKER_ID)


if __name__ == "__main__":
    main_loop()

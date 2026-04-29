"""
HTTP dispatcher that fronts the job registry.

Three endpoints, mounted under `/api/jobs` in `server.py`:

  POST   /api/jobs                  body: {kind, params, external_id?}
                                     → either runs in-process (no Redis) and
                                       returns SSE, or enqueues to Redis and
                                       streams pubsub events back.

  GET    /api/jobs/{job_id}/stream  → re-attach to an in-flight job's stream
                                       (useful when SSE drops mid-paint).

  POST   /api/jobs/{job_id}/cancel  → publish texel:cancel:{job_id}.

The legacy /api/generate, /api/chat, /api/reference, /api/tileset routes stay
in place for the standalone engine UI; they continue to work and now share
the in-process path with the new dispatcher.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from . import Event, JobContext, get_handler, list_kinds, parse_params

router = APIRouter()


# ── Cancel coordination ──
#
# Workers (and the in-process runner) check `is_canceled(job_id)` between
# steps. We use a Redis key when REDIS_URL is set so any worker / API node
# can flip the flag, and a process-local set otherwise.

_local_canceled: set[str] = set()


def _redis_or_none():
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    import redis as _r
    return _r.from_url(url, decode_responses=True)


def is_canceled(job_id: str) -> bool:
    rd = _redis_or_none()
    if rd is None:
        return job_id in _local_canceled
    return rd.exists(f"texel:cancel:{job_id}") > 0


def request_cancel(job_id: str) -> None:
    rd = _redis_or_none()
    if rd is None:
        _local_canceled.add(job_id)
        return
    rd.set(f"texel:cancel:{job_id}", "1", ex=3600)
    rd.publish(f"texel:cancel:{job_id}", "1")


def _make_cancel_check(job_id: str):
    def _check() -> bool:
        return is_canceled(job_id)
    return _check


# ── SSE serialization ──

def event_to_sse(ev: Event) -> str:
    return f"event: {ev.name}\ndata: {json.dumps(ev.data)}\n\n"


# ── Models ──

class JobCreate(BaseModel):
    kind: str
    params: dict[str, Any]
    external_id: str | None = None    # cloud-supplied UUID; passed to webhooks


# ── Routes ──

@router.get("/api/jobs/kinds")
def list_registered_kinds():
    return {"kinds": list_kinds()}


@router.post("/api/jobs")
def create_job(body: JobCreate):
    try:
        params = parse_params(body.kind, body.params)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    # Use the cloud-supplied external_id as the engine job_id when present.
    # This keeps a single ID space across the cloud, the engine HTTP layer,
    # the Redis queue, the SSE pubsub channel, and the worker webhook.
    job_id = body.external_id or str(uuid.uuid4())
    ctx = JobContext(
        job_id=job_id,
        external_id=body.external_id or job_id,
        cancel_check=_make_cancel_check(job_id),
    )

    rd = _redis_or_none()
    if rd is not None:
        # Cloud / scaled mode: enqueue and stream from pubsub. The legacy
        # `texel:jobs` queue is reused so existing workers pick this up.
        return _enqueue_and_stream(rd, job_id, body.kind, params, ctx)

    # Self-hosted / single-process mode: run inline and stream the iterator.
    return StreamingResponse(
        _stream_inline(body.kind, params, ctx),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/jobs/{job_id}/stream")
def stream_job(job_id: str):
    """Re-attach to an in-flight job. Only meaningful in Redis-backed mode."""
    rd = _redis_or_none()
    if rd is None:
        raise HTTPException(status_code=400, detail="Stream re-attach requires REDIS_URL")
    return StreamingResponse(
        _sse_from_pubsub(rd, job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    request_cancel(job_id)
    return {"ok": True, "job_id": job_id}


# ── Stream helpers ──

def _stream_inline(kind: str, params: BaseModel, ctx: JobContext) -> Iterator[str]:
    """Run the handler in-process and yield SSE bytes."""
    handler = get_handler(kind)()
    yield event_to_sse(Event(name="job", data={"id": ctx.job_id, "kind": kind}))
    try:
        for ev in handler.run(params, ctx):
            yield event_to_sse(ev)
    except Exception as e:
        yield event_to_sse(Event(name="error", data={"message": str(e)}))


def _enqueue_and_stream(rd, job_id: str, kind: str, params: BaseModel, ctx: JobContext):
    """Push a job onto the Redis queue and stream its pubsub events to the client."""
    sub = _subscribe_pubsub(rd, job_id)

    rd.lpush("texel:jobs", json.dumps({
        "type": "job",                # new generic shape
        "kind": kind,
        "job_id": job_id,
        "external_id": ctx.external_id,
        "params": params.model_dump(),
    }))

    return StreamingResponse(
        _sse_from_subscribed(sub, job_id, kind),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _subscribe_pubsub(rd, job_id: str):
    sub = rd.pubsub()
    sub.subscribe(f"texel:events:{job_id}")
    sub.get_message(timeout=1)        # consume the subscribe-ack
    return sub


def _sse_from_pubsub(rd, job_id: str) -> Iterator[str]:
    sub = _subscribe_pubsub(rd, job_id)
    yield event_to_sse(Event(name="job", data={"id": job_id, "reattached": True}))
    yield from _sse_from_subscribed(sub, job_id, kind=None)


def _sse_from_subscribed(sub, job_id: str, kind: str | None) -> Iterator[str]:
    if kind is not None:
        yield event_to_sse(Event(name="job", data={"id": job_id, "kind": kind}))
    try:
        for msg in sub.listen():
            if msg["type"] != "message":
                continue
            data = msg["data"]
            if data == "__done__":
                break
            yield data
    finally:
        try:
            sub.unsubscribe()
            sub.close()
        except Exception:
            pass

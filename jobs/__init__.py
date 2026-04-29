"""
Texel Studio — generic Job system.

A `Job` represents one unit of asynchronous work the engine knows how to run.
Each kind ("sprite.generate", "sprite.chat", "sprite.reference",
"sprite.tileset", "sprite.from_photo", ...) is a `JobHandler` subclass
registered against the registry. The engine dispatches to the right handler
purely by the `kind` field on an incoming job payload — there's no per-kind
HTTP route anymore.

Adding a new feature (e.g. photo→pixelart) is one new file under jobs/ that
registers a handler. No changes to the dispatcher, no changes to the worker
loop, no changes to the cloud API.

This module is import-time safe — registering a handler only stores a class
reference. Handlers may be heavy (require network, AI clients) but they only
instantiate when a job actually runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Iterator

from pydantic import BaseModel


# ── Event types emitted by handlers ──
#
# A handler is a coroutine of `Event`s. The dispatcher fans them out to
# whatever transport the caller wants (SSE in HTTP mode, Redis pub/sub
# in worker mode, callbacks in self-host mode).

@dataclass
class Event:
    name: str       # "log" | "progress" | "result" | "error" | "canceled"
    data: dict[str, Any] = field(default_factory=dict)


def log(message: str, **extra: Any) -> Event:
    return Event(name="log", data={"message": message, **extra})


def progress(pixel_data: list[list[int]] | None = None, **extra: Any) -> Event:
    payload: dict[str, Any] = dict(extra)
    if pixel_data is not None:
        payload["pixel_data"] = pixel_data
    return Event(name="progress", data=payload)


def result(**payload: Any) -> Event:
    return Event(name="result", data=payload)


def error(message: str, **extra: Any) -> Event:
    return Event(name="error", data={"message": message, **extra})


def canceled(**extra: Any) -> Event:
    return Event(name="canceled", data=dict(extra))


# ── Job context ──
#
# Carries cross-cutting concerns into the handler: the job's external_id (the
# cloud's UUID, used for webhook callbacks), a cancel-check callable, and an
# optional per-job logger. Keeps handler signatures simple while letting us
# add new context fields later without touching every handler.

@dataclass
class JobContext:
    job_id: str                                 # engine-side job id
    external_id: str | None = None              # cloud-supplied UUID (jobs.id in Supabase)
    cancel_check: Callable[[], bool] = lambda: False
    extra: dict[str, Any] = field(default_factory=dict)


# ── Handler base ──

class JobHandler:
    """Base class for job handlers.

    Subclasses set:
      kind: ClassVar[str]            -- registry key, e.g. "sprite.generate"
      Params: type[BaseModel]        -- pydantic schema for params

    Subclasses implement:
      run(self, params, ctx) -> Iterator[Event]

    `params` is already validated and parsed when run() is called.
    """

    kind: ClassVar[str] = ""
    Params: ClassVar[type[BaseModel]]

    def run(self, params: BaseModel, ctx: JobContext) -> Iterator[Event]:
        raise NotImplementedError


# ── Registry ──

_registry: dict[str, type[JobHandler]] = {}


def register_job(kind: str):
    """Decorator: register a JobHandler subclass under `kind`."""
    def _wrap(cls: type[JobHandler]) -> type[JobHandler]:
        cls.kind = kind
        _registry[kind] = cls
        return cls
    return _wrap


def get_handler(kind: str) -> type[JobHandler]:
    if kind not in _registry:
        raise KeyError(f"Unknown job kind: {kind!r}. Registered: {sorted(_registry)}")
    return _registry[kind]


def list_kinds() -> list[str]:
    return sorted(_registry)


def parse_params(kind: str, raw: dict[str, Any]) -> BaseModel:
    handler_cls = get_handler(kind)
    return handler_cls.Params(**raw)


# ── Eagerly load built-in handlers ──
#
# Importing these modules registers them via the @register_job decorator.
# Keep imports inside this function so a circular import in one handler
# doesn't break the whole module.

def _load_builtins() -> None:
    from . import sprite_generate    # noqa: F401
    from . import sprite_chat        # noqa: F401
    from . import sprite_reference   # noqa: F401
    from . import sprite_tileset     # noqa: F401
    from . import sprite_from_photo  # noqa: F401


_load_builtins()

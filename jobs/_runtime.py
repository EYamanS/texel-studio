"""
Internal helpers for job handlers.

The shape we want for a handler is:

    def run(self, params, ctx) -> Iterator[Event]:
        ...

But many internal engine functions (run_agent_stream, the Gemini reference
generator) are *synchronous* and produce progress via callbacks, not yields.
This module provides the bridge: the handler kicks off the sync work in a
thread and yields Events out of a Queue as the worker thread populates it.

This is the same pattern as server.py:_run_agent_sse, factored out so every
handler can use it without re-implementing thread management.
"""

from __future__ import annotations

import queue as queue_mod
import threading
import traceback
from typing import Any, Callable, Iterator

from . import Event, error


class _Sentinel:
    """Marker put on the queue to signal end-of-stream."""


_DONE = _Sentinel()


class EventBridge:
    """Thread-safe queue of Events that handlers can emit into.

    The handler-side code calls `bridge.emit(event)` from any thread. The
    main thread iterates `bridge.iter_events()` to drain them in order. The
    bridge is closed by calling `bridge.finish()` (or implicitly when the
    worker thread crashes — see `run_in_thread`).
    """

    def __init__(self, timeout_seconds: float = 600.0):
        self._q: queue_mod.Queue = queue_mod.Queue()
        self._timeout = timeout_seconds

    def emit(self, event: Event) -> None:
        self._q.put(event)

    def finish(self) -> None:
        self._q.put(_DONE)

    def iter_events(self) -> Iterator[Event]:
        while True:
            try:
                ev = self._q.get(timeout=self._timeout)
            except queue_mod.Empty:
                yield error(f"Handler timed out (no events for {self._timeout}s)")
                return
            if ev is _DONE:
                return
            yield ev


def run_in_thread(target: Callable[[], Any], bridge: EventBridge) -> threading.Thread:
    """Run `target` in a daemon thread.

    Whatever `target` does, the bridge will be closed afterwards even if
    `target` raises — exceptions are emitted as `error` events first.
    """

    def _wrapped() -> None:
        try:
            target()
        except Exception as e:
            traceback.print_exc()
            bridge.emit(error(str(e), traceback=traceback.format_exc()))
        finally:
            bridge.finish()

    t = threading.Thread(target=_wrapped, daemon=True)
    t.start()
    return t

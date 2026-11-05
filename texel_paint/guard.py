"""
Safety net: kills the process when a run takes too long or uses too much memory
(for example a runaway loop in a drawing operation), so a bad script can never freeze your machine.

Limits (override with environment variables):
    TEXEL_MAX_SECONDS   default 60
    TEXEL_MAX_MB        default 1500   (committed memory of this process; Windows only, otherwise time limit only)

The watchdog is a daemon thread that checks every 0.25 s. Pure-Python loops release the GIL regularly,
so it can always step in.
"""

import ctypes
import os
import sys
import threading
import time


class _MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def _memory_mb() -> float:
    """Committed memory of this process in MB (0 where unsupported)."""
    if os.name == "nt":
        try:
            counters = _MemoryCounters()
            counters.cb = ctypes.sizeof(_MemoryCounters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return counters.PagefileUsage / 1048576
        except Exception:
            return 0.0
        return 0.0
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return usage / 1024 if sys.platform != "darwin" else usage / 1048576
    except Exception:
        return 0.0


def start(max_seconds: float | None = None, max_mb: float | None = None) -> None:
    """Start the watchdog thread. Call once at program start."""
    max_seconds = float(os.environ.get("TEXEL_MAX_SECONDS", max_seconds or 60))
    max_mb = float(os.environ.get("TEXEL_MAX_MB", max_mb or 1500))
    began = time.time()

    def watch() -> None:
        while True:
            time.sleep(0.25)
            elapsed, memory = time.time() - began, _memory_mb()
            if elapsed > max_seconds or memory > max_mb:
                reason = (f"{elapsed:.0f}s > {max_seconds:.0f}s" if elapsed > max_seconds
                          else f"{memory:.0f} MB > {max_mb:.0f} MB")
                sys.stderr.write(f"\nABORTED by watchdog ({reason}): probably a runaway loop in an operation. "
                                 f"Check the last ops. Limits: TEXEL_MAX_SECONDS / TEXEL_MAX_MB.\n")
                sys.stderr.flush()
                os._exit(3)

    threading.Thread(target=watch, daemon=True).start()

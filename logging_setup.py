"""
Texel Studio — logging setup.

Logs go to the console and to a rotating file. Engine loggers live under
"texel.*" and follow LOG_LEVEL; third-party libraries stay at INFO (uvicorn
access lines, httpx request lines) and chatty ones are held at WARNING.

Env vars:
  LOG_LEVEL  DEBUG | INFO (default) | WARNING | ERROR
  LOG_FILE   log file path, relative to this directory (default logs/texel.log);
             set it empty (LOG_FILE=) to log to the console only
"""

import logging
import logging.handlers
import os
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"
# Noisy at INFO/DEBUG — and the openai SDK's debug output dumps whole request bodies.
QUIET_LOGGERS = ("openai", "httpcore", "urllib3", "botocore", "PIL", "watchfiles", "multipart", "asyncio")

log_file: Path | None = None
_configured = False


def setup_logging() -> None:
    """Configure logging once per process; later calls are no-ops."""
    global log_file, _configured
    if _configured:
        return
    _configured = True

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    file_setting = os.getenv("LOG_FILE", "logs/texel.log")
    if file_setting:
        path = Path(file_setting)
        if not path.is_absolute():
            path = Path(__file__).parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"))
        log_file = path

    formatter = logging.Formatter(FORMAT, DATEFMT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)

    level = logging.getLevelName(os.getenv("LOG_LEVEL", "INFO").upper())
    logging.getLogger("texel").setLevel(level if isinstance(level, int) else logging.INFO)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

#!/usr/bin/env python3
"""Shared logging factory for Golden News.

Each module calls get_logger(name) once at import time.  Each name gets:
  - a RotatingFileHandler  → logs/{name}.log  (5 MB, 5 backups, DEBUG+)
  - a StreamHandler        → stdout           (INFO+, captured by systemd journal
                                                or by app.py's _stream_subprocess)
"""
import logging
import logging.handlers
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_FMT = "%(asctime)s [%(levelname)-8s] %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for *name*, creating handlers only once."""
    _LOG_DIR.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    fh = logging.handlers.RotatingFileHandler(
        _LOG_DIR / f"{name}.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FMT, datefmt=_DATE))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(_FMT, datefmt=_DATE))

    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.propagate = False
    return logger

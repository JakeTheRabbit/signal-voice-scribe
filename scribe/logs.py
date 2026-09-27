"""Logging to rotating files under ``logs/``.

Logs record what happened (a voice note was queued, took 4 s, was sent) but
never message text, transcripts, names or phone numbers.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup(logs_dir: Path, name: str, console: bool = False, level: int = logging.INFO) -> None:
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = RotatingFileHandler(Path(logs_dir) / f"{name}.log", maxBytes=1_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        root.addHandler(stream)
    # Third-party libraries are chatty at INFO and can include file paths.
    for noisy in ("faster_whisper", "httpx", "huggingface_hub", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

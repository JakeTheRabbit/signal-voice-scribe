"""The engine's heartbeat file, read by the desktop app and ``signal-scribe status``."""
from __future__ import annotations

import os
import time
from pathlib import Path

from .compat import read_json, write_json_atomic

STALE_AFTER_SECONDS = 45


class StatusFile:
    def __init__(self, path: Path, **initial):
        self.path = Path(path)
        self.state = {"pid": os.getpid(), "started_at": time.time(), **initial}

    def update(self, **changes) -> None:
        self.state.update(changes)
        self.state["updated_at"] = time.time()
        try:
            write_json_atomic(self.path, self.state, indent=None)
        except (OSError, ValueError):
            pass  # A missed heartbeat is harmless; the next one retries.


def read(path: Path, now: float | None = None) -> dict | None:
    """The last heartbeat, marked ``stale`` if the engine stopped updating it."""
    state = read_json(path, 256 * 1024)
    if not isinstance(state, dict):
        return None
    now = time.time() if now is None else now
    updated = state.get("updated_at")
    state["stale"] = not isinstance(updated, (int, float)) or now - updated > STALE_AFTER_SECONDS
    return state

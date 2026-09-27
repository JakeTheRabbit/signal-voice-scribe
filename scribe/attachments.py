"""signal-cli's attachment folder, kept as empty as possible.

As a linked device, signal-cli downloads every attachment your account
receives: photos, videos and files as well as voice notes. Signal Scribe only
needs voice notes, and only until they are transcribed, so everything else is
deleted as soon as its message has been seen, and a sweep removes anything
left behind (for example after a crash).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .messages import SAFE_ATTACHMENT_ID

log = logging.getLogger("scribe.attachments")


def find(folder: Path, attachment_id: str) -> Path | None:
    """signal-cli stores ``<id>`` or ``<id>.<extension>``."""
    if not isinstance(attachment_id, str) or not SAFE_ATTACHMENT_ID.fullmatch(attachment_id):
        return None
    exact = folder / attachment_id
    if exact.is_file():
        return exact
    for candidate in folder.glob(f"{attachment_id}.*"):
        if candidate.is_file() and candidate.name.split(".")[0] == attachment_id.split(".")[0]:
            return candidate
    return None


def delete(folder: Path, attachment_ids) -> int:
    removed = 0
    for attachment_id in attachment_ids:
        path = find(folder, attachment_id)
        if path is None:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            log.debug("could not delete an attachment yet; the sweep will retry")
    return removed


def sweep(folder: Path, keep: set[str], older_than: float = 3600, now: float | None = None) -> int:
    """Delete attachments older than ``older_than`` seconds that no job needs."""
    now = time.time() if now is None else now
    if not folder.is_dir():
        return 0
    keep_stems = {item.split(".")[0] for item in keep}
    removed = 0
    for path in folder.iterdir():
        try:
            if (not path.is_file() or path.name.split(".")[0] in keep_stems
                    or now - path.stat().st_mtime < older_than):
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed

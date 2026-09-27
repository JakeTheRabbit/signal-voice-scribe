"""Durable work queue for voice notes.

A voice note is written here the moment signal-cli reports it, before any
slow work starts. If the app is stopped, crashes, or the computer sleeps
mid-transcription, the note is picked up again on the next start instead of
being lost. The job id is derived from the message itself, so a repeated
event can never produce a second transcript.

Finished jobs keep only their id and outcome (for duplicate detection), never
the transcript or the chat details, and are pruned after 30 days.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

PENDING, DONE, FAILED = "pending", "done", "failed"
KEEP_FINISHED_SECONDS = 30 * 86400


@dataclass
class Job:
    id: str
    account: str
    payload: dict
    attempts: int
    result: dict | None
    created_at: float


class JobStore:
    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._added = threading.Event()
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                account TEXT NOT NULL,
                payload TEXT NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                result TEXT,
                error TEXT,
                finished_at REAL)""")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_due ON jobs(state, next_attempt_at)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        try:
            with db:
                db.execute("PRAGMA secure_delete=ON")
                yield db
        finally:
            db.close()

    def enqueue(self, job_id: str, account: str, payload: dict, now: float | None = None) -> bool:
        """Store a new job. Returns False if this voice note was already seen."""
        now = time.time() if now is None else now
        with self._connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO jobs (id, created_at, account, payload, state) VALUES (?,?,?,?,?)",
                (job_id, now, account, json.dumps(payload), PENDING))
            added = cursor.rowcount == 1
        if added:
            self._added.set()
        return added

    def next_due(self, now: float | None = None) -> Job | None:
        now = time.time() if now is None else now
        self._added.clear()  # cleared before looking, so no wake-up is missed
        with self._connect() as db:
            row = db.execute(
                "SELECT id, account, payload, attempts, result, created_at FROM jobs "
                "WHERE state=? AND next_attempt_at<=? ORDER BY created_at LIMIT 1",
                (PENDING, now)).fetchone()
        if not row:
            return None
        return Job(row[0], row[1], json.loads(row[2]), row[3],
                   json.loads(row[4]) if row[4] else None, row[5])

    def wait(self, timeout: float) -> None:
        """Sleep until a job is added (or ``wake`` is called) or ``timeout`` passes."""
        self._added.wait(timeout)

    def wake(self) -> None:
        self._added.set()

    def save_result(self, job_id: str, result: dict) -> None:
        with self._connect() as db:
            db.execute("UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), job_id))

    def retry(self, job_id: str, error: str, delay: float, now: float | None = None,
              count: bool = True) -> int:
        """Try again after ``delay`` seconds. ``count=False`` for waits that aren't failures."""
        now = time.time() if now is None else now
        with self._connect() as db:
            db.execute("UPDATE jobs SET attempts=attempts+?, error=?, next_attempt_at=? WHERE id=?",
                       (1 if count else 0, error, now + delay, job_id))
            row = db.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row[0] if row else 0

    def retry_now(self, error: str) -> None:
        """Make jobs that were waiting for ``error`` to clear due immediately."""
        with self._connect() as db:
            db.execute("UPDATE jobs SET next_attempt_at=0 WHERE state=? AND error=?", (PENDING, error))
        self._added.set()

    def _finish(self, job_id: str, state: str, error: str | None, now: float | None) -> None:
        now = time.time() if now is None else now
        # Drop the transcript and chat details; only the outcome is kept.
        with self._connect() as db:
            db.execute("UPDATE jobs SET state=?, error=?, finished_at=?, payload='{}', result=NULL WHERE id=?",
                       (state, error, now, job_id))

    def complete(self, job_id: str, now: float | None = None) -> None:
        self._finish(job_id, DONE, None, now)

    def fail(self, job_id: str, error: str, now: float | None = None) -> None:
        self._finish(job_id, FAILED, error, now)

    def pending(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM jobs WHERE state=?", (PENDING,)).fetchone()[0]

    def pending_attachments(self) -> set[str]:
        """Attachment ids still needed by unfinished jobs (never swept)."""
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM jobs WHERE state=?", (PENDING,)).fetchall()
        ids = set()
        for (payload,) in rows:
            try:
                attachment = json.loads(payload).get("attachment_id")
            except ValueError:
                continue
            if isinstance(attachment, str):
                ids.add(attachment)
        return ids

    def counts(self, since: float) -> dict:
        with self._connect() as db:
            rows = db.execute("SELECT state, COUNT(*) FROM jobs WHERE created_at>=? GROUP BY state",
                              (since,)).fetchall()
        return {state: count for state, count in rows}

    def prune(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._connect() as db:
            cursor = db.execute("DELETE FROM jobs WHERE state!=? AND finished_at<?",
                                (PENDING, now - KEEP_FINISHED_SECONDS))
            return cursor.rowcount

"""Optional local history of transcripts, with automatic expiry."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re
import shutil
import sqlite3
import stat
import uuid


@dataclass(frozen=True)
class HistoryItem:
    id: str
    created_at: datetime
    expires_at: datetime | None
    conversation: str
    sender: str
    direction: str
    kind: str
    transcript: str
    media_path: Path | None
    duration: float | None = None
    language: str | None = None


COLUMNS = "id, created_at, expires_at, conversation, sender, direction, kind, transcript, media_path, duration, language"


class HistoryStore:
    def __init__(self, database: Path, media_dir: Path):
        self.database = Path(database)
        self.media_dir = Path(media_dir)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS history (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT,
                conversation TEXT NOT NULL, sender TEXT NOT NULL,
                direction TEXT NOT NULL, kind TEXT NOT NULL,
                transcript TEXT NOT NULL, media_path TEXT
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS history_created ON history(created_at DESC)")
            existing = {row[1] for row in db.execute("PRAGMA table_info(history)")}
            for column, kind in (("duration", "REAL"), ("language", "TEXT")):
                if column not in existing:
                    db.execute(f"ALTER TABLE history ADD COLUMN {column} {kind}")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database)
        try:
            with db:
                db.execute("PRAGMA secure_delete=ON")
                yield db
        finally:
            db.close()

    def record(self, conversation, sender, direction, kind, transcript,
               media_path, retention_hours, now=None, duration=None, language=None):
        retention_hours = float(retention_hours or 0)
        if retention_hours == 0:
            return None
        now = now or datetime.now(timezone.utc)
        expires = None if retention_hours < 0 else now + timedelta(hours=retention_hours)
        item_id = uuid.uuid4().hex
        managed = None
        if media_path:
            source = Path(media_path)
            if source.is_file():
                self.media_dir.mkdir(parents=True, exist_ok=True)
                managed = self.media_dir / f"{item_id}{source.suffix.lower()}"
                shutil.copy2(source, managed)
        duration = float(duration) if isinstance(duration, (int, float)) else None
        language = str(language)[:16] if language else None
        with self._connect() as db:
            db.execute(f"INSERT INTO history ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                item_id, now.isoformat(), expires.isoformat() if expires else None,
                str(conversation), str(sender), str(direction), str(kind),
                str(transcript), str(managed) if managed else None, duration, language))
        return HistoryItem(item_id, now, expires, str(conversation), str(sender),
                           str(direction), str(kind), str(transcript), managed, duration, language)

    @staticmethod
    def validate_filters(query="", direction="", kind="", conversation="", limit=500, max_limit=100000):
        if type(limit) is not int or not 1 <= limit <= max_limit:
            raise ValueError(f"limit must be an integer from 1 to {max_limit}")
        if any(not isinstance(value, str) or len(value) > 4096
               for value in (query, direction, kind, conversation)):
            raise ValueError("history filters must be strings of at most 4096 characters")
        if direction not in ("", "incoming", "outgoing"):
            raise ValueError("direction must be incoming or outgoing")
        if kind not in ("", "voice"):
            raise ValueError("kind must be voice")

    def list_items(self, query="", direction="", kind="", conversation="", limit=500):
        self.validate_filters(query, direction, kind, conversation, limit)
        clauses, values = [], []
        if query:
            clauses.append("(transcript LIKE ? OR sender LIKE ? OR conversation LIKE ?)")
            token = f"%{query}%"; values.extend([token, token, token])
        for column, value in (("direction", direction), ("kind", kind), ("conversation", conversation)):
            if value:
                clauses.append(f"{column} = ?"); values.append(value)
        sql = f"SELECT {COLUMNS} FROM history" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        sql += " ORDER BY created_at DESC LIMIT ?"; values.append(int(limit))
        with self._connect() as db:
            rows = db.execute(sql, values).fetchall()
        return [self._item(row) for row in rows]

    def get(self, item_id):
        with self._connect() as db:
            row = db.execute(f"SELECT {COLUMNS} FROM history WHERE id=?", (item_id,)).fetchone()
        return self._item(row) if row else None

    def delete(self, item_id):
        with self._connect() as db:
            row = db.execute("SELECT media_path FROM history WHERE id=?", (item_id,)).fetchone()
            if not row:
                return False
            self._delete_managed(row[0], item_id)
            db.execute("DELETE FROM history WHERE id=?", (item_id,))
        return True

    def clear(self):
        """Delete every item and its retained audio."""
        with self._connect() as db:
            rows = db.execute("SELECT id, media_path FROM history").fetchall()
            for item_id, path in rows:
                self._delete_managed(path, item_id)
            db.execute("DELETE FROM history")
        return len(rows)

    def purge_expired(self, now=None):
        now = now or datetime.now(timezone.utc)
        with self._connect() as db:
            rows = db.execute("SELECT id, media_path FROM history WHERE expires_at IS NOT NULL AND julianday(expires_at) <= julianday(?)",
                              (now.isoformat(),)).fetchall()
            for item_id, path in rows:
                self._delete_managed(path, item_id)
            db.executemany("DELETE FROM history WHERE id=?", ((row[0],) for row in rows))
        return len(rows)

    def conversations(self):
        with self._connect() as db:
            return [row[0] for row in db.execute(
                "SELECT DISTINCT conversation FROM history ORDER BY conversation COLLATE NOCASE")]

    def managed_path(self, raw_path, item_id):
        """Only this row's generated, direct, non-linked regular media file."""
        path = Path(raw_path).absolute()
        root = self.media_dir.absolute()
        if (not isinstance(item_id, str) or not re.fullmatch(r"[0-9a-f]{32}", item_id)
                or path.parent != root or path.stem != item_id
                or path.is_symlink() or root.is_symlink()
                or path.resolve() != path or root.resolve() != root):
            raise ValueError("Audio path is outside managed history")
        try:
            info = path.stat()
        except FileNotFoundError:
            return path
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Audio path is not a managed regular file")
        return path

    def _delete_managed(self, raw_path, item_id):
        if not raw_path:
            return
        try:
            path = self.managed_path(raw_path, item_id)
        except (ValueError, OSError, RuntimeError):
            return
        if path.is_file():
            try:
                fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
                with os.fdopen(fd, "r+b", buffering=0) as target:
                    info = os.fstat(target.fileno())
                    if info.st_nlink != 1 or not stat.S_ISREG(info.st_mode) or not os.path.samestat(info, path.stat()):
                        return
                    size = info.st_size
                    zeros = b"\0" * min(1024 * 1024, max(1, size))
                    remaining = size
                    while remaining:
                        chunk = zeros[:min(len(zeros), remaining)]
                        target.write(chunk); remaining -= len(chunk)
                    target.flush(); os.fsync(target.fileno())
            except OSError:
                pass
            path.unlink(missing_ok=True)

    @staticmethod
    def _item(row):
        return HistoryItem(row[0], datetime.fromisoformat(row[1]),
                           datetime.fromisoformat(row[2]) if row[2] else None,
                           row[3], row[4], row[5], row[6], row[7],
                           Path(row[8]) if row[8] else None, row[9], row[10])

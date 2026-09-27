"""The private API the desktop app calls (JSON lines over stdin/stdout).

Every method is allow-listed, takes exactly its documented fields, and returns
only what the window needs. Creating a service starts nothing.
"""
from __future__ import annotations

import base64
import os
import re
import stat
import threading
import time
from pathlib import Path

from .. import autostart, config as settings_module, doctor, linking, status as engine_status
from ..history.store import HistoryStore
from ..paths import Paths, resolve
from ..signal_cli import linked_accounts
from .errors import ControlFailure

MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_QR_BYTES = 256 * 1024
ID = re.compile(r"[0-9a-f]{32}\Z")
AUDIO_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
               ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
               ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac",
               ".webm": "audio/webm"}


def validate_id(value) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ControlFailure("invalid_params", "History ids are 32 hexadecimal characters")
    return value


class ControlService:
    METHODS = {
        "state.get": set(), "config.get": set(), "config.save": {"config"},
        "history.list": None, "history.conversations": set(), "history.audio": {"id"},
        "history.delete": {"ids"}, "history.clear": set(), "diagnostics.get": set(),
        "link.status": set(), "autostart.get": set(), "autostart.set": {"enabled"},
    }

    def __init__(self, paths: Paths | Path | None = None):
        self.paths = paths if isinstance(paths, Paths) else resolve(paths)
        self._history = None
        self._config_lock = threading.Lock()

    @property
    def history(self) -> HistoryStore:
        if self._history is None:
            self._history = HistoryStore(self.paths.history_db, self.paths.history_media)
        return self._history

    def dispatch(self, method, params=None):
        if not isinstance(method, str) or method not in self.METHODS:
            raise ControlFailure("method_not_allowed", "This operation is not supported")
        params = {} if params is None else params
        if not isinstance(params, dict):
            raise ControlFailure("invalid_params", "Parameters must be an object")
        fields = self.METHODS[method]
        if fields is not None and set(params) != fields:
            raise ControlFailure("invalid_params", "Request fields do not match the command")
        handler = getattr(self, method.replace(".", "_"))
        return handler(**params) if fields is not None else handler(params)

    # ---- state and settings ----------------------------------------------------------

    def state_get(self):
        accounts = linked_accounts(self.paths)
        heartbeat = engine_status.read(self.paths.status_file)
        engine = None
        if heartbeat is not None:
            engine = {key: heartbeat.get(key) for key in (
                "state", "detail", "problem", "signal", "model", "queue", "active", "last",
                "version", "updated_at", "stale")}
        return {
            "linked": bool(accounts),
            "unlinked": bool(accounts) and not all(a.registered for a in accounts),
            "account": accounts[0].label if accounts else "",
            "schema_version": settings_module.SCHEMA_VERSION,
            "engine": engine,
        }

    def config_get(self):
        try:
            return settings_module.read_strict(self.paths.config)
        except settings_module.ConfigError as exc:
            raise ControlFailure("config_unavailable", str(exc)) from exc

    def config_save(self, config):
        if not isinstance(config, dict):
            raise ControlFailure("invalid_config", "Settings must be an object")
        with self._config_lock:
            current = self.config_get()
            merged = settings_module.patch(current, config)
            merged["schema_version"] = settings_module.SCHEMA_VERSION
            try:
                return settings_module.save(self.paths.config, merged)
            except settings_module.ConfigError as exc:
                raise ControlFailure("invalid_config", str(exc)) from exc
            except (OSError, TypeError, ValueError) as exc:
                raise ControlFailure("config_write_failed",
                                     "Settings could not be saved; check permissions and free disk space") from exc

    # ---- history ---------------------------------------------------------------------

    def history_list(self, filters):
        allowed = {"query", "direction", "kind", "conversation", "limit"}
        if set(filters) - allowed:
            raise ControlFailure("invalid_params", "Unknown history filter")
        try:
            HistoryStore.validate_filters(**filters, max_limit=1000)
        except (TypeError, ValueError) as exc:
            raise ControlFailure("invalid_params", str(exc)) from exc
        if not self.paths.history_db.exists():
            return []
        self.history.purge_expired()
        return [{
            "id": item.id, "created_at": item.created_at.isoformat(),
            "expires_at": item.expires_at.isoformat() if item.expires_at else None,
            "conversation": item.conversation, "sender": item.sender,
            "direction": item.direction, "kind": item.kind, "transcript": item.transcript,
            "duration": item.duration, "language": item.language,
            "media_available": self._media_available(item),
        } for item in self.history.list_items(**filters)]

    def _media_available(self, item):
        if not item.media_path:
            return False
        try:
            return self.history.managed_path(item.media_path, item.id).is_file()
        except (ValueError, OSError, RuntimeError):
            return False

    def history_conversations(self):
        if not self.paths.history_db.exists():
            return []
        self.history.purge_expired()
        return self.history.conversations()

    def history_delete(self, ids):
        if not isinstance(ids, list) or len(ids) > 1000:
            raise ControlFailure("invalid_params", "Send at most 1000 history ids")
        for item_id in ids:
            validate_id(item_id)
        return {"deleted": sum(1 for item_id in dict.fromkeys(ids) if self.history.delete(item_id))}

    def history_clear(self):
        if not self.paths.history_db.exists():
            return {"deleted": 0}
        return {"deleted": self.history.clear()}

    def history_audio(self, id):
        validate_id(id)
        self.history.purge_expired()
        item = self.history.get(id)
        if not item or not item.media_path:
            raise ControlFailure("media_unavailable", "The audio was not kept or has expired")
        try:
            path = self.history.managed_path(item.media_path, item.id)
        except (ValueError, OSError, RuntimeError) as exc:
            raise ControlFailure("path_denied", "Audio is outside Signal Scribe's history folder") from exc
        mime = AUDIO_TYPES.get(path.suffix.lower(), "audio/mp4" if not path.suffix else None)
        if not mime:
            raise ControlFailure("media_unavailable", "This audio format can't be played here")
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if info.st_nlink != 1 or not stat.S_ISREG(info.st_mode) or not os.path.samestat(info, path.stat()):
                    raise ControlFailure("path_denied", "The audio file changed; refresh history")
                if info.st_size > MAX_AUDIO_BYTES:
                    raise ControlFailure("media_too_large", "The audio is larger than 16 MB")
                audio = source.read(MAX_AUDIO_BYTES + 1)
        except OSError as exc:
            raise ControlFailure("media_unavailable", "The audio could not be read") from exc
        if len(audio) > MAX_AUDIO_BYTES:
            raise ControlFailure("media_too_large", "The audio is larger than 16 MB")
        return {"data_url": f"data:{mime};base64,{base64.b64encode(audio).decode('ascii')}"}

    # ---- diagnostics, linking, autostart --------------------------------------------

    def diagnostics_get(self):
        return {"checks": doctor.as_dicts(doctor.run(self.paths))}

    def link_status(self):
        status = linking.read_status(self.paths)
        state = status.get("state") if isinstance(status.get("state"), str) else "idle"
        expires = status.get("expires_at")
        result = {"state": state}
        if state == "waiting" and isinstance(expires, (int, float)) and time.time() > expires:
            state = result["state"] = "failed"
            result["reason"] = "expired"
        elif state == "failed":
            result["reason"] = str(status.get("reason") or "failed")[:40]
        elif state == "linked":
            result["account"] = str(status.get("account") or "")[:64]
        if state == "waiting":
            try:
                image = linking.qr_path(self.paths).read_bytes()
            except OSError:
                image = b""  # not written yet, or linking just ended
            if 0 < len(image) <= MAX_QR_BYTES:
                result["qr"] = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
        return result

    def autostart_get(self):
        target = autostart.desktop_target()
        return {"available": target is not None, "enabled": autostart.is_enabled(self.paths.root)}

    def autostart_set(self, enabled):
        if type(enabled) is not bool:
            raise ControlFailure("invalid_params", "enabled must be true or false")
        target = autostart.desktop_target()
        if target is None:
            raise ControlFailure("autostart_unavailable", "Start at login is only available in the desktop app")
        try:
            autostart.set_enabled(enabled, target, owner=self.paths.root)
        except OSError as exc:
            raise ControlFailure("autostart_failed", "Start at login could not be changed") from exc
        return {"available": True, "enabled": autostart.is_enabled(self.paths.root)}

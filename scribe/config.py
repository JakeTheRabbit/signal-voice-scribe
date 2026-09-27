"""Settings: defaults, tolerant loading for the engine, strict checks for saves."""
from __future__ import annotations

import copy
import json
import logging
import math
import re
from pathlib import Path

from .compat import read_json, write_json_atomic

SCHEMA_VERSION = 3
MAX_CONFIG_BYTES = 256 * 1024

MODELS = (
    "auto", "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "medium", "medium.en", "large-v3", "large-v3-turbo", "distil-large-v3",
)
DEVICES = ("auto", "cpu", "cuda")
COMPUTE_TYPES = ("auto", "int8", "int8_float16", "float16", "float32")
DELIVERY_MODES = ("note_to_self", "chat")
THEMES = ("system", "light", "dark")
LANGUAGE = re.compile(r"[a-z]{2,3}\Z")
MAX_RETENTION_HOURS = 876000  # 100 years; -1 means "until I delete it"

DEFAULTS = {
    "schema_version": SCHEMA_VERSION,
    "transcription": {
        "model": "auto",
        "device": "auto",
        "compute_type": "auto",
        "language": None,
        "incoming": True,
        "outgoing": True,
        "groups": True,
        "audio_files": False,
        "max_minutes": 60,
    },
    "delivery": {
        "mode": "note_to_self",
        "notify": True,
        "failure_notices": True,
    },
    "history": {
        "retention_hours": 0,
        "conversation_retention_hours": {},
        "keep_audio": True,
    },
    "desktop": {
        "theme": "system",
        "start_engine_on_launch": True,
    },
}

log = logging.getLogger("scribe.config")


class ConfigError(ValueError):
    """A setting is invalid. The message names the field and is safe to show."""


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


def merge(base: dict, override: dict) -> dict:
    """Deep-merge ``override`` onto ``base``; unknown keys are preserved."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _bool(value, field):
    if type(value) is not bool:
        raise ConfigError(f"{field} must be true or false")


def _choice(value, choices, field):
    if value not in choices:
        raise ConfigError(f"{field} must be one of: {', '.join(choices)}")


def _hours(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or not (
            value == -1 or 0 <= value <= MAX_RETENTION_HOURS):
        raise ConfigError(f"{field} must be -1 (keep) or 0 to {MAX_RETENTION_HOURS} hours")


def validate(config: dict) -> None:
    """Raise ConfigError for the first invalid known setting."""
    if not isinstance(config, dict):
        raise ConfigError("settings must be a JSON object")
    for section in ("transcription", "delivery", "history", "desktop"):
        if not isinstance(config.get(section, {}), dict):
            raise ConfigError(f"{section} must be an object")
    version = config.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION or type(version) is not int:
        raise ConfigError(f"schema_version must be {SCHEMA_VERSION}")

    t = config.get("transcription", {})
    if "model" in t:
        _choice(t["model"], MODELS, "transcription.model")
    if "device" in t:
        _choice(t["device"], DEVICES, "transcription.device")
    if "compute_type" in t:
        _choice(t["compute_type"], COMPUTE_TYPES, "transcription.compute_type")
    if t.get("language") is not None and (
            not isinstance(t["language"], str) or not LANGUAGE.fullmatch(t["language"])):
        raise ConfigError("transcription.language must be empty (auto-detect) or a code such as en or de")
    for key in ("incoming", "outgoing", "groups", "audio_files"):
        if key in t:
            _bool(t[key], f"transcription.{key}")
    if "max_minutes" in t and (type(t["max_minutes"]) is not int or not 1 <= t["max_minutes"] <= 600):
        raise ConfigError("transcription.max_minutes must be a whole number from 1 to 600")

    d = config.get("delivery", {})
    if "mode" in d:
        _choice(d["mode"], DELIVERY_MODES, "delivery.mode")
    for key in ("notify", "failure_notices"):
        if key in d:
            _bool(d[key], f"delivery.{key}")

    h = config.get("history", {})
    if "retention_hours" in h:
        _hours(h["retention_hours"], "history.retention_hours")
    overrides = h.get("conversation_retention_hours", {})
    if not isinstance(overrides, dict) or len(overrides) > 1000:
        raise ConfigError("history.conversation_retention_hours must be an object of at most 1000 entries")
    for name, hours in overrides.items():
        if not isinstance(name, str) or not 0 < len(name) <= 256:
            raise ConfigError("history.conversation_retention_hours keys must be 1-256 characters")
        _hours(hours, "history.conversation_retention_hours entry")
    if "keep_audio" in h:
        _bool(h["keep_audio"], "history.keep_audio")

    desktop = config.get("desktop", {})
    if "theme" in desktop:
        _choice(desktop["theme"], THEMES, "desktop.theme")
    if "start_engine_on_launch" in desktop:
        _bool(desktop["start_engine_on_launch"], "desktop.start_engine_on_launch")


def sanitize(config: dict) -> tuple[dict, list[str]]:
    """Replace each invalid known setting with its default instead of failing.

    The engine uses this so a hand-edited typo degrades one setting, not the app.
    """
    clean = merge(defaults(), config if isinstance(config, dict) else {})
    clean["schema_version"] = SCHEMA_VERSION
    problems: list[str] = []
    for section, values in DEFAULTS.items():
        if not isinstance(values, dict):
            continue
        if not isinstance(clean.get(section), dict):
            problems.append(f"{section} must be an object")
            clean[section] = copy.deepcopy(values)
            continue
        for key, default in values.items():
            try:
                validate({"schema_version": SCHEMA_VERSION, section: {key: clean[section].get(key, default)}})
            except ConfigError as exc:
                problems.append(str(exc))
                clean[section][key] = copy.deepcopy(default)
    return clean, problems


def load(path: Path) -> tuple[dict, list[str]]:
    """Settings for the engine: defaults merged with the file, never raising."""
    path = Path(path)
    if not path.exists():
        return defaults(), []
    raw = read_json(path, MAX_CONFIG_BYTES)
    if not isinstance(raw, dict):
        return defaults(), ["config.json is unreadable; using default settings"]
    config, problems = sanitize(raw)
    for problem in problems:
        log.warning("config: %s; using the default for that setting", problem)
    return config, problems


def read_strict(path: Path) -> dict:
    """Settings for the desktop: the file must be readable (missing is fine)."""
    path = Path(path)
    if not path.exists():
        return defaults()
    raw = read_json(path, MAX_CONFIG_BYTES)
    if not isinstance(raw, dict):
        raise ConfigError("config.json is not valid JSON; fix or delete it to restore defaults")
    merged = merge(defaults(), raw)
    merged["schema_version"] = SCHEMA_VERSION
    return merged


def save(path: Path, config: dict) -> dict:
    validate(config)
    encoded = json.dumps(config, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ConfigError("settings are too large")
    write_json_atomic(Path(path), config)
    return config


def patch(current: dict, update: dict) -> dict:
    """Apply a partial update. The retention override map is replaced whole."""
    merged = merge(current, update)
    overrides = (update.get("history") or {}).get("conversation_retention_hours") if isinstance(
        update.get("history"), dict) else None
    if isinstance(overrides, dict):
        merged["history"]["conversation_retention_hours"] = copy.deepcopy(overrides)
    return merged

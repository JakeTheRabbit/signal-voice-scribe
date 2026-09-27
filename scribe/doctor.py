"""Health checks shared by ``signal-scribe doctor`` and the desktop's Diagnostics page."""
from __future__ import annotations

import shutil
import sys
from dataclasses import asdict, dataclass

from . import __version__, config as settings_module, status as engine_status
from .paths import Paths
from .signal_cli import MIN_JAVA, find_java, java_version, linked_accounts, signal_cli_home, signal_cli_version
from .transcription import MODEL_SIZES_MB, model_cached, plan

OK, WARNING, ERROR = "ok", "warning", "error"


@dataclass
class Check:
    name: str
    status: str
    detail: str


def run(paths: Paths) -> list[Check]:
    """Local checks only; nothing here contacts the network."""
    checks: list[Check] = []

    def add(name, state, detail):
        checks.append(Check(name, state, detail))

    add("Signal Scribe", OK, f"Version {__version__}, Python {sys.version.split()[0]}")

    try:
        config = settings_module.read_strict(paths.config)
        settings_module.validate(config)
        add("Settings", OK, "Valid" if paths.config.exists() else "Using defaults")
    except settings_module.ConfigError as exc:
        config = settings_module.defaults()
        add("Settings", ERROR, str(exc))

    accounts = linked_accounts(paths)
    if not accounts:
        add("Signal link", WARNING, "Not linked yet. Use Link Signal (or `signal-scribe link`).")
    elif not all(account.registered for account in accounts):
        add("Signal link", ERROR, "Signal removed this computer from your linked devices. Link it again.")
    else:
        add("Signal link", OK, f"Linked to {', '.join(a.label for a in accounts)}")

    java = find_java(paths)
    if java is not None:
        add("Java", OK, f"Java {java_version(java)} found")
    elif (signal_cli_home(paths) / "lib").is_dir():
        add("Java", ERROR, f"Java {MIN_JAVA} or newer is required. Re-run the installer to download it.")
    else:
        add("Java", OK, "Not needed (native signal-cli)" if (signal_cli_home(paths) / "signal-cli").is_file()
            else "Checked together with signal-cli")

    version = signal_cli_version(paths)
    if version:
        add("signal-cli", OK, f"Version {version}")
    else:
        add("signal-cli", ERROR, "Not installed. Re-run the installer.")

    settings = config.get("transcription", {})
    chosen = plan(settings)
    if model_cached(chosen.model, paths.models):
        add("Whisper model", OK, f"{chosen.model} on {chosen.device.upper()} ({chosen.compute_type})")
    else:
        size = MODEL_SIZES_MB.get(chosen.model, "?")
        add("Whisper model", WARNING,
            f"{chosen.model} is not downloaded yet (~{size} MB). It downloads on first use, "
            "or run `signal-scribe download-model`.")

    free = shutil.disk_usage(paths.home).free / 1024 ** 3
    add("Disk space", OK if free > 2 else WARNING, f"{free:.1f} GB free")

    heartbeat = engine_status.read(paths.status_file)
    if heartbeat is None or heartbeat.get("stale") or heartbeat.get("state") == "stopped":
        add("Engine", WARNING, "Not running")
    elif heartbeat.get("state") == "needs_attention":
        # Not being linked yet is expected after installing; the Signal link check says what to do.
        add("Engine", WARNING if heartbeat.get("problem") == "not_linked" else ERROR,
            heartbeat.get("detail") or "Needs attention")
    else:
        pending = (heartbeat.get("queue") or {}).get("pending")
        add("Engine", OK, f"{heartbeat.get('detail', 'Running')}"
            + (f"; {pending} voice note(s) waiting" if pending else ""))
    return checks


def as_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(check) for check in checks]

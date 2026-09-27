"""Linking this computer to your Signal account, the same way Signal Desktop does.

signal-cli prints a ``sgnl://linkdevice`` address; it is shown as a QR code for
the phone to scan (Signal → Settings → Linked devices → Link new device).

The desktop app runs ``link.py`` and polls ``data/link/status.json``; the
command line prints the QR code in the terminal. The QR image is deleted as
soon as linking ends.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .compat import no_window, read_json, write_json_atomic
from .paths import Paths
from .runtime_lock import ReceiverBusyError, ReceiverLease
from .signal_cli import SignalCliMissing, base_command, linked_accounts

log = logging.getLogger("scribe.link")

LINK_TIMEOUT_SECONDS = 300
DEVICE_NAME = "Signal Scribe"
URI = re.compile(r"(sgnl://linkdevice\S+|tsdevice:/\S+)")


def status_path(paths: Paths) -> Path:
    return paths.link_dir / "status.json"


def qr_path(paths: Paths) -> Path:
    return paths.link_dir / "qr.png"


def write_status(paths: Paths, state: str, **extra) -> None:
    write_json_atomic(status_path(paths), {"state": state, "updated_at": time.time(), **extra}, indent=None)


def read_status(paths: Paths) -> dict:
    status = read_json(status_path(paths), 64 * 1024)
    return status if isinstance(status, dict) else {"state": "idle"}


def qr_image(uri: str, path: Path) -> None:
    import qrcode
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    code.add_data(uri)
    code.make(fit=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    code.make_image(fill_color="black", back_color="white").save(path)


def print_qr(uri: str) -> None:
    import qrcode
    code = qrcode.QRCode(border=2)
    code.add_data(uri)
    code.make(fit=True)
    code.print_ascii(invert=True)


def _reason(lines: list[str]) -> str:
    text = " ".join(lines).lower()
    if "timeout" in text or "timed out" in text:
        return "expired"
    if "already exists" in text or "useralreadyexists" in text:
        return "already_linked"
    if "unknownhost" in text or "connect" in text and "failed" in text or "network" in text:
        return "network"
    return "failed"


def run(paths: Paths, device_name: str = DEVICE_NAME, timeout: float = LINK_TIMEOUT_SECONDS,
        on_uri: Callable[[str], None] | None = None) -> int:
    """Link and return 0 on success. Status is written for the desktop app throughout."""
    paths.ensure()
    qr = qr_path(paths)
    qr.unlink(missing_ok=True)
    try:
        lease = ReceiverLease(paths.data).acquire()
    except ReceiverBusyError:
        write_status(paths, "failed", reason="engine_running")
        return 3
    try:
        write_status(paths, "starting", started_at=time.time())
        try:
            command = base_command(paths) + ["link", "-n", device_name]
        except SignalCliMissing:
            write_status(paths, "failed", reason="runtime_missing")
            return 2
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", **no_window())
        expired = threading.Event()

        def expire():
            expired.set()
            proc.kill()

        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        other: list[str] = []
        try:
            for line in proc.stdout:
                match = URI.search(line)
                if match:
                    qr_image(match.group(1), qr)
                    write_status(paths, "waiting", expires_at=time.time() + timeout)
                    if on_uri:
                        on_uri(match.group(1))
                elif line.strip():
                    other.append(line.strip()[:300])
            code = proc.wait()
        finally:
            timer.cancel()
        if code == 0:
            accounts = linked_accounts(paths)
            write_status(paths, "linked", account=accounts[-1].label if accounts else "")
            log.info("linked successfully")
            return 0
        reason = "expired" if expired.is_set() else _reason(other[-5:])
        write_status(paths, "failed", reason=reason)
        log.warning("linking did not complete (%s)", reason)
        return 1
    except OSError:
        write_status(paths, "failed", reason="runtime_missing")
        return 2
    finally:
        qr.unlink(missing_ok=True)
        lease.close()


def forget(paths: Paths) -> int:
    """Delete this computer's Signal keys (after it was removed on the phone)."""
    try:
        lease = ReceiverLease(paths.data).acquire()
    except ReceiverBusyError:
        return 3
    try:
        failures = 0
        for account in linked_accounts(paths):
            result = subprocess.run(
                base_command(paths) + ["-a", account.id, "deleteLocalAccountData", "--ignore-registered"],
                capture_output=True, text=True, timeout=120, **no_window())
            failures += result.returncode != 0
        return 1 if failures else 0
    finally:
        lease.close()


def main() -> int:
    """Entry point used by the desktop app (``link.py``)."""
    from .logs import setup
    from .paths import resolve
    paths = resolve().ensure()
    setup(paths.logs, "link")
    return run(paths)

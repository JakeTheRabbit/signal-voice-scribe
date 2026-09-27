"""Running signal-cli: locating it, linked accounts, and a JSON-RPC client.

Signal Scribe talks to Signal only through signal-cli running as a linked
device. The engine keeps one ``signal-cli jsonRpc`` process alive and reads
events from its stdout; requests and their responses are matched by id.
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .compat import no_window, read_json
from .paths import IS_MAC, IS_WINDOWS, Paths

log = logging.getLogger("scribe.signal")

MIN_JAVA = 25
# What signal-cli logs when Signal rejects this linked device (it was removed
# from the phone's Linked devices list). The account file is then re-checked.
UNLINKED_HINT = re.compile(r"AuthorizationFailedException|relinking required")


class SignalCliMissing(RuntimeError):
    pass


class RpcError(RuntimeError):
    def __init__(self, message: str, code=None):
        super().__init__(message)
        self.code = code


class RpcTimeout(RpcError):
    pass


class RpcClosed(RpcError):
    pass


# --- locating Java and signal-cli ----------------------------------------------------

def java_candidates(paths: Paths) -> list[Path]:
    exe = "java.exe" if IS_WINDOWS else "java"
    found: list[Path] = []
    if os.environ.get("SIGNAL_SCRIBE_JAVA"):
        found.append(Path(os.environ["SIGNAL_SCRIBE_JAVA"]))
    jre = paths.runtime / "jre"
    found += [jre / "bin" / exe, jre / "Contents" / "Home" / "bin" / exe]
    if os.environ.get("JAVA_HOME"):
        found.append(Path(os.environ["JAVA_HOME"]) / "bin" / exe)
    system = shutil.which("java")
    if system:
        found.append(Path(system))
    return found


def java_version(java: Path) -> int | None:
    """Major version of a Java runtime, or None if it cannot be run."""
    try:
        result = subprocess.run([str(java), "-version"], capture_output=True, text=True,
                                timeout=30, **no_window())
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'version "(\d+)(?:\.(\d+))?', result.stderr + result.stdout)
    if not match:
        return None
    major = int(match.group(1))
    return int(match.group(2)) if major == 1 and match.group(2) else major


def find_java(paths: Paths, minimum: int = MIN_JAVA) -> Path | None:
    for candidate in java_candidates(paths):
        if candidate.is_file() and (java_version(candidate) or 0) >= minimum:
            return candidate
    return None


def signal_cli_home(paths: Paths) -> Path:
    override = os.environ.get("SIGNAL_SCRIBE_SIGNAL_CLI")
    return Path(override) if override else paths.runtime / "signal-cli"


def signal_cli_version(paths: Paths) -> str | None:
    """Version recorded by the installer (avoids starting a JVM just to ask)."""
    marker = read_json(signal_cli_home(paths) / "signal-scribe.json")
    if isinstance(marker, dict) and isinstance(marker.get("version"), str):
        return marker["version"]
    jars = sorted((signal_cli_home(paths) / "lib").glob("signal-cli-*.jar"))
    match = re.search(r"signal-cli-(\d[\w.]*)\.jar", jars[-1].name) if jars else None
    return match.group(1) if match else None


def base_command(paths: Paths) -> list[str]:
    """The signal-cli command line up to (not including) the subcommand."""
    home = signal_cli_home(paths)
    native = home / ("signal-cli.exe" if IS_WINDOWS else "signal-cli")
    lib = home / "lib"
    if lib.is_dir() and any(lib.glob("*.jar")):
        java = find_java(paths)
        if java is None:
            raise SignalCliMissing(f"Java {MIN_JAVA}+ was not found. Re-run the installer.")
        command = [str(java), "--enable-native-access=ALL-UNNAMED"]
        if IS_MAC:
            command.append("-Dapple.awt.UIElement=true")  # never show a Dock icon
        command += ["-classpath", str(lib / "*"), "org.asamk.signal.Main"]
    elif native.is_file():
        command = [str(native)]
    else:
        raise SignalCliMissing("signal-cli was not found. Re-run the installer.")
    return command + ["--config", str(paths.data)]


# --- linked accounts ------------------------------------------------------------------

@dataclass(frozen=True)
class Account:
    number: str | None
    aci: str | None
    registered: bool = True

    @property
    def id(self) -> str:
        """What signal-cli expects in the ``account`` parameter."""
        return self.number or self.aci or ""

    @property
    def label(self) -> str:
        return self.number or "Linked account"


def _still_registered(account_file: Path) -> bool:
    """signal-cli records ``registered: false`` once Signal rejects the device,
    which is what happens after the phone removes it from Linked devices."""
    state = read_json(account_file, 16 * 1024 * 1024)
    return not (isinstance(state, dict) and state.get("registered") is False)


def linked_accounts(paths: Paths) -> list[Account]:
    """Accounts signal-cli has stored. ``--config data`` keeps them in data/data."""
    store = paths.data / "data"
    raw = read_json(store / "accounts.json", 1024 * 1024)
    accounts = raw.get("accounts") if isinstance(raw, dict) else None
    result: list[Account] = []
    for row in accounts if isinstance(accounts, list) else []:
        if not isinstance(row, dict):
            continue
        number = row.get("number") if isinstance(row.get("number"), str) and row["number"].strip() else None
        aci = row.get("uuid") or row.get("aci")
        aci = aci if isinstance(aci, str) and aci.strip() else None
        path = row.get("path")
        registered = True
        if isinstance(path, str) and re.fullmatch(r"[\w.-]{1,64}", path):
            registered = _still_registered(store / path)
        if number or aci:
            result.append(Account(number, aci, registered))
    return result


# --- JSON-RPC client --------------------------------------------------------------------

class JsonRpcClient:
    """One ``signal-cli jsonRpc`` process.

    ``on_event`` receives every notification (for example ``receive``) on the
    reader thread, so it must return quickly. ``request`` is thread-safe.
    """

    def __init__(self, paths: Paths, on_event: Callable[[dict], None],
                 on_stderr: Callable[[str], None] | None = None, command: list[str] | None = None):
        self.paths = paths
        self.on_event = on_event
        self.on_stderr = on_stderr
        self.command = command or base_command(paths) + [
            "--output=json", "jsonRpc", "--ignore-avatars", "--ignore-stickers", "--ignore-stories"]
        self.proc: subprocess.Popen | None = None
        self._ids = itertools.count(1)
        self._write_lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", bufsize=1, **no_window())
        log.info("signal-cli started (pid %s)", self.proc.pid)
        for target, name in ((self._read_stdout, "signal-stdout"), (self._read_stderr, "signal-stderr")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                log.debug("signal-cli: ignored a non-JSON line")
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message:
                try:
                    self.on_event(message)
                except Exception:
                    log.exception("signal-cli: event handler failed")
                continue
            waiter = None
            if isinstance(message.get("id"), int):
                with self._pending_lock:
                    waiter = self._pending.pop(message["id"], None)
            if waiter is not None:
                waiter.put(message)
        self._fail_pending()

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        log_file = self.paths.logs / "signal-cli.log"
        try:
            if log_file.stat().st_size > 2_000_000:  # keep one previous copy, like the other logs
                os.replace(log_file, log_file.with_name("signal-cli.log.1"))
        except OSError:
            pass
        with open(log_file, "a", encoding="utf-8", errors="replace") as sink:
            for line in self.proc.stderr:
                sink.write(line)
                sink.flush()
                if self.on_stderr:
                    try:
                        self.on_stderr(line.rstrip())
                    except Exception:
                        log.exception("signal-cli: stderr handler failed")

    def _fail_pending(self) -> None:
        with self._pending_lock:
            waiters, self._pending = list(self._pending.values()), {}
        for waiter in waiters:
            waiter.put(None)

    def request(self, method: str, params: dict | None = None, timeout: float = 30):
        if not self.running:
            raise RpcClosed("signal-cli is not running")
        request_id = next(self._ids)
        waiter: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = waiter
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params:
            payload["params"] = params
        try:
            with self._write_lock:
                assert self.proc and self.proc.stdin
                self.proc.stdin.write(json.dumps(payload) + "\n")
                self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise RpcClosed("signal-cli stopped accepting requests") from exc
        try:
            response = waiter.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise RpcTimeout(f"signal-cli did not answer {method} within {timeout:.0f}s") from None
        if response is None:
            raise RpcClosed("signal-cli exited before answering")
        if "error" in response:
            error = response.get("error") or {}
            raise RpcError(str(error.get("message") or "signal-cli returned an error")[:300], error.get("code"))
        return response.get("result")

    def wait(self, timeout: float | None = None) -> int | None:
        if self.proc is None:
            return None
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def close(self, timeout: float = 10) -> None:
        """Ask signal-cli to exit cleanly (EOF on stdin), then force it."""
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        if self.wait(timeout) is None:
            log.warning("signal-cli did not exit in %.0fs; stopping it", timeout)
            self.proc.kill()
            self.wait(5)
        for thread in self._threads:
            thread.join(timeout=2)
        self._fail_pending()

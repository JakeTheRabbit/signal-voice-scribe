"""The transcription engine: voice notes in from signal-cli, text back out.

Threads:
* signal-cli's reader thread turns ``receive`` events into durable jobs.
* one worker transcribes and delivers jobs, oldest first.
* a housekeeping thread refreshes contact names, sweeps attachments, expires
  history and writes the heartbeat the desktop app shows.
The main thread keeps signal-cli running and restarts it with backoff.

Exit codes: 0 stopped, 2 needs the user (not linked, unlinked, broken
install), 3 another engine already owns this install, 1 unexpected error.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import __version__, attachments
from . import config as settings_module
from .compat import hide_console, utf8_streams
from .history.store import HistoryStore
from .jobs import Job, JobStore
from .logs import setup as setup_logging
from .messages import VoiceNote, failure_message, transcript_message, voice_notes
from .paths import Paths, resolve
from .runtime_lock import ReceiverBusyError, ReceiverLease
from .signal_cli import (UNLINKED_HINT, JsonRpcClient, RpcClosed, RpcError, RpcTimeout, SignalCliMissing,
                         linked_accounts)
from .status import StatusFile
from .transcription import AudioTooLong, AudioUnreadable, Cancelled, Transcriber

log = logging.getLogger("scribe.engine")

EXIT_OK, EXIT_ERROR, EXIT_NEEDS_USER, EXIT_BUSY = 0, 1, 2, 3
TRANSCRIBE_ATTEMPTS = 3
DELIVERY_WINDOW_SECONDS = 48 * 3600
RECONNECT_DELAYS = (2, 5, 10, 30, 60, 120, 300)
HEARTBEAT_SECONDS = 10
PING_EVERY_SECONDS = 300
IDLE_WAIT_SECONDS = 5


def _backoff(attempt: int, base: float = 30, cap: float = 900) -> float:
    return min(cap, base * (2 ** max(0, attempt)))


class Engine:
    def __init__(self, paths: Paths, config: dict, *, client_factory=JsonRpcClient,
                 transcriber: Transcriber | None = None):
        self.paths = paths
        self.config = config
        self.client_factory = client_factory
        self.jobs = JobStore(paths.jobs_db)
        self.transcriber = transcriber or Transcriber(paths.models, config["transcription"])
        self.stop_event = threading.Event()
        self.client: JsonRpcClient | None = None
        self.names: dict[str, str] = {}
        self._history: HistoryStore | None = None
        self._recheck_link = threading.Event()
        self._idle = "Starting"  # what the status says between voice notes
        self._state = {"state": "starting", "detail": "Starting", "problem": None,
                       "signal": {"connected": False, "since": None}, "active": None, "last": None}
        self.heartbeat = StatusFile(paths.status_file, version=__version__)
        self._publish_lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    # ---- status ------------------------------------------------------------------------

    def publish(self, **changes) -> None:
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        try:
            queue = {"pending": self.jobs.pending(), "today": self.jobs.counts(midnight)}
        except Exception:
            queue = {"pending": None, "today": {}}
        with self._publish_lock:
            self._state.update(changes)
            self.heartbeat.update(**self._state, queue=queue, model=self.transcriber.status)

    def needs_user(self, problem: str, detail: str) -> int:
        log.warning("needs attention: %s", problem)
        self.publish(state="needs_attention", problem=problem, detail=detail,
                     signal={"connected": False, "since": None})
        return EXIT_NEEDS_USER

    # ---- events from signal-cli (reader thread; must stay fast) ----------------------

    def on_event(self, message: dict) -> None:
        if message.get("method") != "receive":
            return
        params = message.get("params") or {}
        if "envelope" not in params and isinstance(params.get("result"), dict):
            params = {"account": params.get("account"), **params["result"]}
        notes, discard = voice_notes(params, self.config["transcription"], self.names)
        for note in notes:
            if self.jobs.enqueue(note.job_id, note.account, note.to_payload()):
                log.info("queued an %s voice note", note.direction)
            else:
                log.info("ignored a repeated voice note")
        if discard:
            attachments.delete(self.paths.attachments, discard)

    def on_stderr(self, line: str) -> None:
        if UNLINKED_HINT.search(line):
            self._recheck_link.set()

    # ---- worker ------------------------------------------------------------------------

    def work_forever(self) -> None:
        while not self.stop_event.is_set():
            job = self.jobs.next_due()
            if job is None:
                self.jobs.wait(IDLE_WAIT_SECONDS)
                continue
            try:
                self.process(job)
            except Cancelled:
                log.info("stopping part-way through a voice note; it will resume next start")
                return
            except Exception:
                log.exception("unexpected error while handling a voice note")
                self.jobs.retry(job.id, "internal_error", 300)
            finally:
                self._state["active"] = None
                self.publish(detail=self._idle)

    def process(self, job: Job) -> None:
        note = VoiceNote.from_payload(job.payload)
        result = job.result
        if result is None:
            result = self.transcribe(job, note)
            if result is None:
                return  # retry already scheduled
            self.jobs.save_result(job.id, result)
        if result.get("transcript") is not None and not result.get("history_saved"):
            self.record_history(note, result)
            result["history_saved"] = True
            self.jobs.save_result(job.id, result)
        if result.get("message") and not self.deliver(job, note, result):
            return
        self.finish(job, note, result)

    def transcribe(self, job: Job, note: VoiceNote) -> dict | None:
        path = attachments.find(self.paths.attachments, note.attachment_id)
        if path is None:
            return self.failed(note, "the audio file was not downloaded")
        try:
            if not self.transcriber.status.get("ready"):
                self.publish(detail="Loading the Whisper model")
            self.transcriber.load()
        except Exception as exc:
            # A model problem is not this note's fault: wait, don't count it.
            log.warning("Whisper model unavailable (%s); will retry", type(exc).__name__)
            self.jobs.retry(job.id, "model_unavailable", 300, count=False)
            self.publish(problem="model_unavailable",
                         detail="The Whisper model could not be loaded. Check your internet connection "
                                "for the one-time download, or free up disk space.")
            return None
        self._state["active"] = {"direction": note.direction, "since": time.time()}
        self.publish(detail="Transcribing a voice note", problem=None)
        try:
            transcript = self.transcriber.transcribe(
                path, self.config["transcription"].get("max_minutes"), self.stop_event.is_set)
        except Cancelled:
            raise
        except AudioTooLong as exc:
            return self.failed(note, f"it is {exc.minutes:.0f} minutes long; the limit is {exc.limit}")
        except AudioUnreadable:
            return self.failed(note, "the audio could not be read")
        except Exception as exc:
            attempts = self.jobs.retry(job.id, "transcription_error", _backoff(job.attempts))
            log.warning("transcription failed (%s), attempt %d of %d", type(exc).__name__, attempts,
                        TRANSCRIBE_ATTEMPTS)
            if attempts < TRANSCRIBE_ATTEMPTS:
                return None
            return self.failed(note, "transcription kept failing")
        log.info("transcribed %.0fs of audio in %.1fs", transcript.duration, transcript.elapsed)
        self._state["last"] = {"at": time.time(), "direction": note.direction,
                               "audio_seconds": round(transcript.duration, 1),
                               "seconds": round(transcript.elapsed, 1)}
        in_chat = self.config["delivery"].get("mode") == "chat"
        return {
            "transcript": transcript.text, "language": transcript.language,
            "duration": transcript.duration, "path": str(path),
            "message": transcript_message(note, transcript.text, transcript.language,
                                          transcript.duration, in_chat),
            "notice": False,
        }

    def failed(self, note: VoiceNote, reason: str) -> dict:
        log.warning("could not transcribe a voice note: %s", reason)
        notify = self.config["delivery"].get("failure_notices", True)
        return {"transcript": None, "failed": reason, "notice": True,
                "message": failure_message(note, reason) if notify else None}

    def delivery_params(self, note: VoiceNote, result: dict) -> dict:
        delivery = self.config["delivery"]
        if delivery.get("mode") == "chat" and not result.get("notice"):
            params = {**note.target, "message": result["message"],
                      "quoteTimestamp": note.timestamp, "quoteAuthor": note.author}
        else:
            params = {"noteToSelf": True, "message": result["message"]}
            if delivery.get("notify", True):
                params["notifySelf"] = True
        return {"account": note.account, **params}

    def deliver(self, job: Job, note: VoiceNote, result: dict) -> bool:
        """Send the text. False means a retry was scheduled or the job was given up."""
        client = self.client
        if client is None or not client.running:
            error, delay = "signal_unavailable", 300
        else:
            try:
                client.request("send", self.delivery_params(note, result), timeout=90)
                log.info("sent a %s", "failure notice" if result.get("notice") else "transcript")
                return True
            except (RpcTimeout, RpcClosed, RpcError) as exc:
                log.warning("sending failed (%s); will retry", type(exc).__name__)
                error, delay = "send_failed", _backoff(job.attempts, 30, 600)
        if time.time() - job.created_at > DELIVERY_WINDOW_SECONDS:
            log.warning("giving up on delivering a transcript after 48 hours")
            self.jobs.fail(job.id, error)
            attachments.delete(self.paths.attachments, [note.attachment_id])
        else:
            # Waiting for Signal to reconnect isn't a failure; it is released on connect.
            self.jobs.retry(job.id, error, delay, count=error != "signal_unavailable")
            if error == "signal_unavailable" and self.client is not None:
                self.jobs.retry_now(error)  # connected while we were scheduling
        return False

    def finish(self, job: Job, note: VoiceNote, result: dict) -> None:
        if result.get("transcript") is None:
            self.jobs.fail(job.id, result.get("failed", "failed")[:80])
        else:
            self.jobs.complete(job.id)
        attachments.delete(self.paths.attachments, [note.attachment_id])

    # ---- history -----------------------------------------------------------------------

    def retention_hours(self, conversation: str) -> float:
        history = self.config["history"]
        overrides = history.get("conversation_retention_hours") or {}
        return float(overrides.get(conversation, history.get("retention_hours", 0)) or 0)

    @property
    def history(self) -> HistoryStore:
        if self._history is None:
            self._history = HistoryStore(self.paths.history_db, self.paths.history_media)
        return self._history

    def record_history(self, note: VoiceNote, result: dict) -> None:
        hours = self.retention_hours(note.chat)
        if hours == 0:
            return
        if note.expires_in:
            # Never keep a copy longer than the disappearing message itself.
            limit = note.expires_in / 3600
            hours = limit if hours < 0 else min(hours, limit)
        media = result.get("path") if self.config["history"].get("keep_audio", True) else None
        try:
            self.history.record(note.chat, note.sender, note.direction, "voice", result["transcript"],
                                media, hours, duration=result.get("duration"),
                                language=result.get("language"))
        except Exception:
            log.exception("could not save to history")

    # ---- housekeeping ------------------------------------------------------------------

    def refresh_names(self) -> None:
        client = self.client
        if client is None:
            return
        names: dict[str, str] = {}
        for account in {a.id for a in linked_accounts(self.paths)}:
            try:
                for contact in client.request("listContacts", {"account": account}, timeout=60) or []:
                    profile = contact.get("profile") or {}
                    name = (contact.get("name") or contact.get("nickName") or " ".join(
                        filter(None, (profile.get("givenName"), profile.get("familyName")))))
                    if name:
                        for key in (contact.get("uuid"), contact.get("number")):
                            if key:
                                names[key] = str(name)[:120]
                for group in client.request("listGroups", {"account": account}, timeout=60) or []:
                    if group.get("id") and group.get("name"):
                        names[group["id"]] = str(group["name"])[:120]
            except (RpcError, AttributeError, TypeError):
                log.info("could not refresh contact names; keeping the previous ones")
                return
        self.names = names

    def housekeeping(self) -> None:
        last_names = last_sweep = 0.0
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            now = time.time()
            if self.client is not None and now - last_names > 1800:
                last_names = now
                self.refresh_names()
            if now - last_sweep > 600:
                last_sweep = now
                try:
                    attachments.sweep(self.paths.attachments, self.jobs.pending_attachments())
                    self.jobs.prune()
                    if self.paths.history_db.exists():
                        removed = self.history.purge_expired()
                        if removed:
                            log.info("history: deleted %d expired item(s)", removed)
                except Exception:
                    log.exception("housekeeping pass failed")
            self.publish()

    def warm_up(self) -> None:
        try:
            self.transcriber.load()
            self.publish()
        except Exception as exc:
            log.warning("Whisper model not ready yet (%s)", type(exc).__name__)
            self.publish(problem="model_unavailable",
                         detail="The Whisper model could not be loaded yet. It will be retried when a "
                                "voice note arrives.")

    # ---- main loop ---------------------------------------------------------------------

    def _start(self, target, name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def still_linked(self) -> bool:
        accounts = linked_accounts(self.paths)
        return bool(accounts) and all(account.registered for account in accounts)

    def run(self) -> int:
        if not linked_accounts(self.paths):
            return self.needs_user("not_linked", "Link Signal Scribe to your Signal account first.")
        self.publish(state="starting", detail="Starting")
        self._start(self.work_forever, "scribe-worker")
        self._start(self.housekeeping, "scribe-housekeeping")
        self._start(self.warm_up, "scribe-warm-up")
        failures = 0
        try:
            while not self.stop_event.is_set():
                if not self.still_linked():
                    return self.needs_user(
                        "unlinked", "Signal no longer accepts this computer (it was removed from Linked "
                                    "devices on your phone). Link it again.")
                try:
                    client = self.client_factory(self.paths, self.on_event, self.on_stderr)
                    client.start()
                except SignalCliMissing as exc:
                    return self.needs_user("runtime_missing", str(exc))
                except OSError as exc:
                    log.error("could not start signal-cli: %s", type(exc).__name__)
                    return self.needs_user("runtime_missing", "signal-cli could not be started. Re-run the installer.")
                started = time.monotonic()
                self.client = client
                self._idle = "Listening for voice notes"
                self.publish(state="running", detail=self._idle,
                             signal={"connected": True, "since": time.time()})
                threading.Thread(target=self.refresh_names, daemon=True).start()
                self.jobs.retry_now("signal_unavailable")
                last_ping, missed = time.monotonic(), 0
                while not self.stop_event.is_set() and client.running:
                    if self._recheck_link.wait(1):
                        self._recheck_link.clear()
                        if not self.still_linked():
                            break
                    if time.monotonic() - last_ping > PING_EVERY_SECONDS:
                        last_ping = time.monotonic()
                        try:
                            client.request("version", timeout=30)
                            missed = 0
                        except RpcTimeout:
                            missed += 1
                            if missed >= 2:
                                log.warning("signal-cli stopped responding; restarting it")
                                break
                        except RpcError:
                            pass
                self.client = None
                client.close(timeout=10)
                if self.stop_event.is_set():
                    break
                lived = time.monotonic() - started
                failures = 0 if lived > 120 else failures + 1
                delay = RECONNECT_DELAYS[min(failures, len(RECONNECT_DELAYS) - 1)]
                log.warning("signal-cli stopped after %.0fs; restarting in %ds", lived, delay)
                self._idle = "Reconnecting to Signal"
                self.publish(state="reconnecting", detail=self._idle,
                             signal={"connected": False, "since": None})
                self.stop_event.wait(delay)
        finally:
            self.shutdown()
        return EXIT_OK

    def stop(self) -> None:
        self.stop_event.set()
        self.jobs.wake()

    def shutdown(self) -> None:
        self.stop()
        client, self.client = self.client, None
        if client is not None:
            client.close(timeout=10)
        for thread in self._threads:
            thread.join(timeout=15)
        state = self._state.get("state")
        self.publish(state=state if state == "needs_attention" else "stopped",
                     detail=self._state.get("detail") if state == "needs_attention" else "Stopped",
                     signal={"connected": False, "since": None}, active=None)


def _watch_parent_pipe(engine: Engine) -> None:
    """The desktop app closes our stdin to ask for a clean stop (works on every OS)."""
    def watch():
        try:
            while sys.stdin.read(4096):
                pass
        except (OSError, ValueError):
            pass
        engine.stop()
    threading.Thread(target=watch, name="scribe-parent-pipe", daemon=True).start()


def main(root: Path | None = None, console: bool = False) -> int:
    paths = resolve(root).ensure()
    if console:
        utf8_streams()
    setup_logging(paths.logs, "engine", console=console)
    if not console:
        hide_console()
    log.info("Signal Scribe %s engine starting", __version__)
    config, problems = settings_module.load(paths.config)
    try:
        lease = ReceiverLease(paths.data).acquire()
    except ReceiverBusyError as exc:
        log.error("%s", exc)
        if console:
            print(exc, file=sys.stderr)
        return EXIT_BUSY
    try:
        engine = Engine(paths, config)
        if problems:
            engine.publish(detail="Some settings were invalid and use defaults: " + "; ".join(problems)[:300])
        for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"):
            if hasattr(signal, name):
                try:
                    signal.signal(getattr(signal, name), lambda *_: engine.stop())
                except (OSError, ValueError):
                    pass
        if os.environ.get("SIGNAL_SCRIBE_PARENT_PIPE") == "1":
            _watch_parent_pipe(engine)
        return engine.run()
    except Exception:
        log.exception("engine crashed")
        return EXIT_ERROR
    finally:
        lease.close()

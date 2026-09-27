"""The engine end to end, with a fake signal-cli and a fake Whisper model."""
import threading
import time

import pytest

from scribe import config, engine as engine_module, status
from scribe.engine import EXIT_NEEDS_USER, EXIT_OK, Engine
from scribe.history.store import HistoryStore
from scribe.jobs import JobStore
from scribe.messages import job_id
from scribe.signal_cli import RpcError
from scribe.transcription import AudioUnreadable, Cancelled, Transcript

from conftest import ACCOUNT, FRIEND, link_account
from test_messages import NOW_MS, incoming, outgoing, voice


class FakeClient:
    def __init__(self, paths, on_event, on_stderr=None):
        self.on_event = on_event
        self.sent = []
        self.fail_sends = 0
        self._running = False

    def start(self):
        self._running = True

    @property
    def running(self):
        return self._running

    def request(self, method, params=None, timeout=30):
        if method == "send":
            if self.fail_sends:
                self.fail_sends -= 1
                raise RpcError("rate limited")
            self.sent.append(params)
            return {"timestamp": 1}
        if method in ("listContacts", "listGroups"):
            return []
        return {}

    def close(self, timeout=10):
        self._running = False


class FakeWhisper:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or ["hello there"]
        self.calls = 0
        self.status = {"model": "tiny", "device": "cpu", "ready": True}
        self.fallback = None

    def load(self):
        return None

    def transcribe(self, path, max_minutes=None, should_stop=lambda: False):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException) or isinstance(outcome, type):
            raise outcome() if isinstance(outcome, type) else outcome
        if outcome == "wait-for-stop":
            while not should_stop():
                time.sleep(0.01)
            raise Cancelled()
        return Transcript(outcome, "en", 8.0, 0.1)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(engine_module, "IDLE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(engine_module, "_backoff", lambda *args, **kwargs: 0.05)


def wait_for(condition, timeout=20):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the engine"
        time.sleep(0.02)


class Harness:
    def __init__(self, paths, settings=None, whisper=None):
        self.paths = paths
        self.clients = []
        self.whisper = whisper or FakeWhisper()
        settings = config.merge(config.defaults(), settings or {})
        self.engine = Engine(paths, settings, client_factory=self.factory, transcriber=self.whisper)
        self.result = None

    def factory(self, *args):
        client = FakeClient(*args)
        self.clients.append(client)
        return client

    def __enter__(self):
        self.thread = threading.Thread(target=lambda: setattr(self, "result", self.engine.run()))
        self.thread.start()
        wait_for(lambda: self.clients and self.clients[-1].running)
        return self

    @property
    def client(self):
        return self.clients[-1]

    def deliver(self, params, attachment="note1.m4a"):
        self.paths.attachments.mkdir(parents=True, exist_ok=True)
        (self.paths.attachments / attachment).write_bytes(b"fake audio")
        self.client.on_event({"method": "receive", "params": params})

    def __exit__(self, *exc):
        self.engine.stop()
        self.thread.join(40)
        assert not self.thread.is_alive()


def test_voice_note_goes_to_note_to_self_and_the_audio_is_deleted(paths):
    link_account(paths)
    with Harness(paths) as h:
        paths.attachments.mkdir(parents=True, exist_ok=True)
        (paths.attachments / "photo.jpg").write_bytes(b"someone's photo")
        h.deliver(incoming([voice(), {"id": "photo.jpg", "contentType": "image/jpeg"}],
                           timestamp=int(time.time() * 1000)))
        assert not (paths.attachments / "photo.jpg").exists()  # deleted as soon as it is seen
        wait_for(lambda: h.client.sent)
        assert h.client.sent[0] == {"account": ACCOUNT, "noteToSelf": True, "notifySelf": True,
                                    "message": "🎤 Sam · 0:08\nhello there"}
        wait_for(lambda: not (paths.attachments / "note1.m4a").exists())
        heartbeat = status.read(paths.status_file)
        assert heartbeat["state"] == "running" and heartbeat["signal"]["connected"]
    assert h.result == EXIT_OK
    assert status.read(paths.status_file)["state"] == "stopped"


def test_chat_mode_replies_to_the_voice_note(paths):
    link_account(paths)
    with Harness(paths, {"delivery": {"mode": "chat"}}) as h:
        h.deliver(outgoing([voice()]))
        wait_for(lambda: h.client.sent)
    sent = h.client.sent[0]
    assert sent["recipient"] == [FRIEND] and sent["quoteTimestamp"] == NOW_MS
    assert sent["quoteAuthor"] == "aci-self" and sent["message"].startswith("🎤 Transcript · 0:08")


def test_repeated_events_are_transcribed_once(paths):
    link_account(paths)
    with Harness(paths) as h:
        h.deliver(incoming([voice()]))
        wait_for(lambda: h.client.sent)
        h.deliver(incoming([voice()]))
        time.sleep(0.3)
    assert h.whisper.calls == 1 and len(h.client.sent) == 1


def test_failed_sends_are_retried(paths):
    link_account(paths)
    with Harness(paths) as h:
        h.client.fail_sends = 2
        h.deliver(incoming([voice()]))
        wait_for(lambda: h.client.sent)
    assert h.whisper.calls == 1  # the transcript was kept, not re-transcribed


def test_repeated_transcription_errors_end_in_a_notice(paths):
    link_account(paths)
    with Harness(paths, whisper=FakeWhisper(RuntimeError, RuntimeError, RuntimeError)) as h:
        h.deliver(incoming([voice()]))
        wait_for(lambda: h.client.sent)
    assert h.whisper.calls == 3
    assert "Couldn't transcribe" in h.client.sent[0]["message"]


def test_unreadable_audio_can_fail_silently(paths):
    link_account(paths)
    with Harness(paths, {"delivery": {"failure_notices": False}}, FakeWhisper(AudioUnreadable)) as h:
        h.deliver(incoming([voice()]))
        wait_for(lambda: not (paths.attachments / "note1.m4a").exists())
    assert h.client.sent == []
    assert JobStore(paths.jobs_db).pending() == 0


def test_history_never_outlives_a_disappearing_message(paths):
    link_account(paths)
    with Harness(paths, {"history": {"retention_hours": -1}}) as h:
        h.deliver(incoming([voice()], expiresInSeconds=3600))
        wait_for(lambda: h.client.sent)
    [item] = HistoryStore(paths.history_db, paths.history_media).list_items()
    assert item.transcript == "hello there" and item.duration == 8.0
    lifetime = (item.expires_at - item.created_at).total_seconds()
    assert 3590 <= lifetime <= 3610
    assert item.media_path and item.media_path.read_bytes() == b"fake audio"


def test_jobs_left_by_a_crash_are_finished_after_restart(paths):
    link_account(paths)
    note_id = job_id(ACCOUNT, FRIEND, NOW_MS, "note1.m4a")
    from scribe.messages import voice_notes
    [note], _ = voice_notes(incoming([voice()]), config.defaults()["transcription"])
    JobStore(paths.jobs_db).enqueue(note_id, ACCOUNT, note.to_payload())
    paths.attachments.mkdir(parents=True, exist_ok=True)
    (paths.attachments / "note1.m4a").write_bytes(b"fake audio")
    with Harness(paths) as h:
        wait_for(lambda: h.client.sent)
    assert h.client.sent[0]["message"].endswith("hello there")


def test_stopping_mid_transcription_keeps_the_job(paths):
    link_account(paths)
    with Harness(paths, whisper=FakeWhisper("wait-for-stop")) as h:
        h.deliver(incoming([voice()]))
        wait_for(lambda: h.whisper.calls == 1)
    assert JobStore(paths.jobs_db).pending() == 1
    assert (paths.attachments / "note1.m4a").exists()


def test_not_linked_asks_for_the_user(paths):
    h = Harness(paths)
    assert h.engine.run() == EXIT_NEEDS_USER
    assert status.read(paths.status_file)["problem"] == "not_linked"


def test_removed_on_the_phone_asks_to_link_again(paths):
    link_account(paths, registered=False)
    h = Harness(paths)
    assert h.engine.run() == EXIT_NEEDS_USER
    assert status.read(paths.status_file)["problem"] == "unlinked"

import sqlite3
import threading
import time

from scribe.jobs import JobStore


def test_enqueue_is_idempotent(tmp_path):
    jobs = JobStore(tmp_path / "jobs.sqlite3")
    assert jobs.enqueue("a" * 32, "acct", {"attachment_id": "x.m4a"})
    assert not jobs.enqueue("a" * 32, "acct", {"attachment_id": "x.m4a"})
    assert jobs.pending() == 1


def test_jobs_come_back_oldest_first_and_respect_retry_delay(tmp_path):
    jobs = JobStore(tmp_path / "jobs.sqlite3")
    jobs.enqueue("old", "acct", {}, now=100)
    jobs.enqueue("new", "acct", {}, now=200)
    assert jobs.next_due(now=300).id == "old"
    assert jobs.retry("old", "send_failed", delay=60, now=300) == 1
    assert jobs.next_due(now=300).id == "new"
    jobs.complete("new")
    assert jobs.next_due(now=359) is None
    assert jobs.next_due(now=361).id == "old"


def test_finished_jobs_keep_no_transcript_or_chat_details(tmp_path):
    jobs = JobStore(tmp_path / "jobs.sqlite3")
    jobs.enqueue("job", "acct", {"chat": "Sam", "attachment_id": "x.m4a"})
    jobs.save_result("job", {"transcript": "private words"})
    jobs.complete("job")
    row = sqlite3.connect(tmp_path / "jobs.sqlite3").execute("SELECT payload, result, state FROM jobs").fetchone()
    assert row == ("{}", None, "done")
    assert not jobs.enqueue("job", "acct", {})  # still remembered, so no duplicate transcript


def test_pending_attachments_and_prune(tmp_path):
    jobs = JobStore(tmp_path / "jobs.sqlite3")
    jobs.enqueue("keep", "acct", {"attachment_id": "keep.m4a"}, now=0)
    jobs.enqueue("gone", "acct", {"attachment_id": "gone.m4a"}, now=0)
    jobs.fail("gone", "failed", now=10)
    assert jobs.pending_attachments() == {"keep.m4a"}
    assert jobs.prune(now=10 + 31 * 86400) == 1
    assert jobs.pending() == 1


def test_wait_wakes_up_when_a_job_arrives(tmp_path):
    jobs = JobStore(tmp_path / "jobs.sqlite3")
    assert jobs.next_due() is None
    threading.Timer(0.1, lambda: jobs.enqueue("job", "acct", {})).start()
    started = time.monotonic()
    jobs.wait(5)
    assert time.monotonic() - started < 4.5  # woken early, not after the 5 s timeout
    assert jobs.next_due().id == "job"

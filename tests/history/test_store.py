from datetime import datetime, timedelta, timezone

from scribe.history.store import HistoryStore


def test_record_copies_media_into_managed_directory(tmp_path):
    source = tmp_path / "source.aac"; source.write_bytes(b"voice")
    store = HistoryStore(tmp_path / "history.sqlite3", tmp_path / "media")
    item = store.record("Gary", "Gary", "incoming", "voice", "hello", source, 24)
    assert item.media_path.parent == tmp_path / "media"
    assert item.media_path.read_bytes() == b"voice"
    assert source.exists()


def test_filter_by_text_direction_and_chat(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3", tmp_path / "media")
    store.record("Gary", "Gary", "incoming", "voice", "dinner tonight", None, 24)
    store.record("Mum", "Me", "outgoing", "transcript", "call tomorrow", None, 24)
    assert [x.conversation for x in store.list_items(query="dinner")] == ["Gary"]
    assert [x.conversation for x in store.list_items(direction="outgoing")] == ["Mum"]
    assert [x.transcript for x in store.list_items(conversation="Gary")] == ["dinner tonight"]


def test_delete_removes_only_managed_media(tmp_path):
    source = tmp_path / "source.aac"; source.write_bytes(b"voice")
    store = HistoryStore(tmp_path / "history.sqlite3", tmp_path / "media")
    item = store.record("Gary", "Gary", "incoming", "voice", "hello", source, 24)
    assert store.delete(item.id)
    assert not item.media_path.exists()
    assert source.exists()


def test_purge_expired_removes_rows_and_media(tmp_path):
    now = datetime(2026, 8, 7, tzinfo=timezone.utc)
    source = tmp_path / "source.aac"; source.write_bytes(b"voice")
    store = HistoryStore(tmp_path / "history.sqlite3", tmp_path / "media")
    item = store.record("Gary", "Gary", "incoming", "voice", "hello", source, 1, now=now)
    assert store.purge_expired(now + timedelta(hours=2)) == 1
    assert not item.media_path.exists()
    assert store.list_items() == []


def test_zero_retention_does_not_store_or_copy(tmp_path):
    source = tmp_path / "source.aac"; source.write_bytes(b"voice")
    store = HistoryStore(tmp_path / "history.sqlite3", tmp_path / "media")
    assert store.record("Gary", "Gary", "incoming", "voice", "hello", source, 0) is None
    assert not (tmp_path / "media").exists()

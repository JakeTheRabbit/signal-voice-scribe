import os

from scribe import attachments


def test_find_exact_name_and_legacy_extension(tmp_path):
    (tmp_path / "abc.m4a").write_bytes(b"x")
    (tmp_path / "legacy.aac").write_bytes(b"x")
    assert attachments.find(tmp_path, "abc.m4a") == tmp_path / "abc.m4a"
    assert attachments.find(tmp_path, "legacy") == tmp_path / "legacy.aac"
    assert attachments.find(tmp_path, "missing") is None


def test_find_refuses_paths_outside_the_folder(tmp_path):
    (tmp_path / "secret.txt").write_text("x")
    folder = tmp_path / "attachments"
    folder.mkdir()
    for bad in ("../secret.txt", "..", "a/b", "", "c:\\x"):
        assert attachments.find(folder, bad) is None


def test_delete_and_sweep_keep_what_jobs_still_need(tmp_path):
    for name in ("voice.m4a", "photo.jpg", "fresh.png"):
        (tmp_path / name).write_bytes(b"x")
    old = 1_000_000
    os.utime(tmp_path / "voice.m4a", (old, old))
    os.utime(tmp_path / "photo.jpg", (old, old))
    assert attachments.sweep(tmp_path, keep={"voice.m4a"}, older_than=3600, now=old + 7200) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fresh.png", "voice.m4a"]
    assert attachments.delete(tmp_path, ["voice.m4a", "not-there"]) == 1

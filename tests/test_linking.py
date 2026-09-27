"""Linking with a fake signal-cli that prints a link address and then 'links'."""
import json
import sys

from scribe import linking
from scribe.runtime_lock import ReceiverLease

FAKE_LINK = r'''
import json, os, sys, time
print("Some startup noise", flush=True)
print("sgnl://linkdevice?uuid=fake&pub_key=fake", flush=True)
time.sleep(float(os.environ.get("FAKE_WAIT", "0.2")))
if os.environ.get("FAKE_FAIL"):
    print("Link request error: Connection timed out", flush=True)
    sys.exit(1)
store = os.path.join(sys.argv[sys.argv.index("--config") + 1], "data")
os.makedirs(store, exist_ok=True)
with open(os.path.join(store, "accounts.json"), "w") as f:
    json.dump({"accounts": [{"path": "1", "number": "+15555550100", "uuid": "aci"}]}, f)
'''


def fake_command(tmp_path, monkeypatch):
    script = tmp_path / "fake_link.py"
    script.write_text(FAKE_LINK, encoding="utf-8")
    monkeypatch.setattr(linking, "base_command",
                        lambda paths: [sys.executable, "-u", str(script), "--config", str(paths.data)])


def test_successful_link_shows_a_code_then_cleans_up(paths, tmp_path, monkeypatch):
    fake_command(tmp_path, monkeypatch)
    seen = []

    def on_uri(uri):
        seen.append((uri, linking.read_status(paths)["state"], linking.qr_path(paths).exists()))

    assert linking.run(paths, on_uri=on_uri) == 0
    assert seen == [("sgnl://linkdevice?uuid=fake&pub_key=fake", "waiting", True)]
    assert linking.read_status(paths)["state"] == "linked"
    assert linking.read_status(paths)["account"] == "+15555550100"
    assert not linking.qr_path(paths).exists()


def test_failures_and_expiry_are_reported(paths, tmp_path, monkeypatch):
    fake_command(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_FAIL", "1")
    assert linking.run(paths) == 1
    assert linking.read_status(paths) | {"updated_at": 0} == {"state": "failed", "reason": "expired",
                                                                "updated_at": 0}
    monkeypatch.delenv("FAKE_FAIL")
    monkeypatch.setenv("FAKE_WAIT", "30")
    assert linking.run(paths, timeout=1) == 1
    assert linking.read_status(paths)["reason"] == "expired"
    assert not linking.qr_path(paths).exists()


def test_linking_waits_for_a_running_engine(paths):
    with ReceiverLease(paths.data):
        assert linking.run(paths) == 3
    assert linking.read_status(paths)["reason"] == "engine_running"


def test_status_file_is_small_json(paths):
    linking.write_status(paths, "starting")
    assert json.loads(linking.status_path(paths).read_text())["state"] == "starting"

"""The JSON-RPC client against a fake signal-cli process (a small Python script)."""
import sys
import threading
import time
from pathlib import Path

import pytest

from scribe import signal_cli
from scribe.signal_cli import JsonRpcClient, RpcClosed, RpcError, RpcTimeout, linked_accounts

from conftest import link_account

FAKE = r'''
import json, sys
print(json.dumps({"jsonrpc": "2.0", "method": "receive", "params": {"account": "+15555550100",
      "envelope": {"sourceUuid": "x", "timestamp": 1, "dataMessage": {"timestamp": 1}}}}), flush=True)
print("not json", flush=True)
sys.stderr.write("WARN something happened\n"); sys.stderr.flush()
for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "slow":
        continue
    if method == "fail":
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -1, "message": "nope"}}), flush=True)
    elif method == "exit":
        sys.exit(0)
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {"echo": request.get("params")}}), flush=True)
'''


@pytest.fixture
def client(paths, tmp_path):
    script = tmp_path / "fake_signal_cli.py"
    script.write_text(FAKE, encoding="utf-8")
    events, errors = [], []
    rpc = JsonRpcClient(paths, events.append, errors.append, command=[sys.executable, "-u", str(script)])
    rpc.start()
    yield rpc, events, errors
    rpc.close(timeout=5)


def wait_for(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.02)


def test_events_requests_and_errors(client, paths):
    rpc, events, errors = client
    wait_for(lambda: events)
    assert events[0]["method"] == "receive"
    assert rpc.request("send", {"message": "hi"}) == {"echo": {"message": "hi"}}
    with pytest.raises(RpcError, match="nope"):
        rpc.request("fail")
    wait_for(lambda: errors)
    assert "WARN" in errors[0]
    assert "WARN something happened" in (paths.logs / "signal-cli.log").read_text(encoding="utf-8")


def test_concurrent_requests_are_matched_by_id(client):
    rpc, _, _ = client
    results = {}

    def ask(n):
        results[n] = rpc.request("echo", {"n": n})["echo"]["n"]

    threads = [threading.Thread(target=ask, args=(n,)) for n in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == {n: n for n in range(20)}


def test_timeouts_and_exit(client):
    rpc, _, _ = client
    with pytest.raises(RpcTimeout):
        rpc.request("slow", timeout=0.3)
    with pytest.raises(RpcClosed):
        rpc.request("exit", timeout=15)
    wait_for(lambda: not rpc.running)
    with pytest.raises(RpcClosed):
        rpc.request("echo")


def test_linked_accounts_and_registration(paths):
    assert linked_accounts(paths) == []
    link_account(paths)
    [account] = linked_accounts(paths)
    assert (account.id, account.registered) == ("+15555550100", True)
    link_account(paths, registered=False)
    assert linked_accounts(paths)[0].registered is False


def test_numberless_accounts_use_their_aci(paths):
    store = paths.data / "data"
    store.mkdir(parents=True)
    (store / "accounts.json").write_text('{"accounts":[{"path":"1","number":null,"uuid":"aci-1"}]}')
    assert linked_accounts(paths)[0].id == "aci-1"


def test_missing_runtime_is_explained(paths, monkeypatch):
    monkeypatch.setenv("SIGNAL_SCRIBE_SIGNAL_CLI", str(paths.home / "nowhere"))
    with pytest.raises(signal_cli.SignalCliMissing):
        signal_cli.base_command(paths)


def test_java_version_parsing(tmp_path, monkeypatch):
    class Result:
        stdout = ""
        stderr = 'openjdk version "25.0.1" 2025-10-21 LTS'
    monkeypatch.setattr(signal_cli.subprocess, "run", lambda *a, **k: Result())
    assert signal_cli.java_version(Path("java")) == 25
    Result.stderr = 'java version "1.8.0_401"'
    assert signal_cli.java_version(Path("java")) == 8


def test_signal_cli_log_is_rotated(paths, tmp_path):
    script = tmp_path / "quiet.py"
    script.write_text("import sys\nsys.stdin.read()\n", encoding="utf-8")
    log = paths.logs / "signal-cli.log"
    log.write_bytes(b"x" * 2_100_000)
    rpc = JsonRpcClient(paths, lambda event: None, command=[sys.executable, str(script)])
    rpc.start()
    rpc.close(timeout=5)
    assert (paths.logs / "signal-cli.log.1").stat().st_size == 2_100_000
    assert log.stat().st_size < 1000

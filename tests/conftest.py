import json
import socket
from pathlib import Path

import pytest

from scribe.paths import Paths

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ACCOUNT = "+15555550100"  # reserved fictional number
FRIEND = "3f0a4f4e-8c3b-4c61-9a73-5a3f1b2c0d11"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests must never contact Signal, Hugging Face or anything else."""
    def refuse(*args, **kwargs):
        raise AssertionError("network access is not allowed in tests")
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def paths(tmp_path):
    return Paths(PROJECT_ROOT, tmp_path).ensure()


def link_account(paths, number=ACCOUNT, registered=True):
    """Write signal-cli's account files the way a successful link leaves them."""
    store = paths.data / "data"
    store.mkdir(parents=True, exist_ok=True)
    (store / "accounts.json").write_text(json.dumps({"accounts": [
        {"path": "123456", "environment": "LIVE", "number": number, "uuid": "aci-self"}], "version": 2}))
    (store / "123456").write_text(json.dumps({"registered": registered, "number": number}))

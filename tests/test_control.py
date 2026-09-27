import base64
import json

import pytest

from control_server import handle_line
from scribe import config, linking
from scribe.control.errors import ControlFailure
from scribe.control.service import ControlService
from scribe.history.store import HistoryStore

from conftest import link_account


@pytest.fixture
def service(paths):
    return ControlService(paths)


def call(service, method, params=None):
    return handle_line(service, json.dumps({"id": 1, "method": method, "params": params or {}}))


def test_unknown_methods_and_fields_are_refused(service):
    assert call(service, "credential.set")["error"]["code"] == "method_not_allowed"
    assert call(service, "config.get", {"extra": 1})["error"]["code"] == "invalid_params"
    assert handle_line(service, "{not json")["error"]["code"] == "invalid_json"
    assert handle_line(service, json.dumps([1]))["error"]["code"] == "invalid_request"


def test_state_reports_link_and_heartbeat(service, paths):
    assert service.dispatch("state.get") == {"linked": False, "unlinked": False, "account": "",
                                             "schema_version": 3, "engine": None}
    link_account(paths, registered=False)
    state = service.dispatch("state.get")
    assert state["linked"] and state["unlinked"] and state["account"] == "+15555550100"


def test_config_round_trip_and_validation(service, paths):
    saved = service.dispatch("config.save", {"config": {"delivery": {"mode": "chat"}}})
    assert saved["delivery"] == {"mode": "chat", "notify": True, "failure_notices": True}
    assert json.loads(paths.config.read_text(encoding="utf-8"))["delivery"]["mode"] == "chat"
    response = call(service, "config.save", {"config": {"transcription": {"model": "huge"}}})
    assert response["error"]["code"] == "invalid_config"
    assert "transcription.model" in response["error"]["message"]
    assert service.dispatch("config.get")["transcription"]["model"] == "auto"


def test_unreadable_config_is_reported_not_overwritten(service, paths):
    paths.config.write_text("{broken", encoding="utf-8")
    assert call(service, "config.get")["error"]["code"] == "config_unavailable"
    assert call(service, "config.save", {"config": {}})["error"]["code"] == "config_unavailable"
    assert paths.config.read_text(encoding="utf-8") == "{broken"


def test_history_listing_audio_and_deletion(service, paths, tmp_path):
    assert service.dispatch("history.list", {}) == []
    audio = tmp_path / "note.m4a"
    audio.write_bytes(b"\x00\x01audio")
    store = HistoryStore(paths.history_db, paths.history_media)
    item = store.record("Sam", "Sam", "incoming", "voice", "hello", audio, 24, duration=4.0, language="en")
    [listed] = service.dispatch("history.list", {"query": "hell"})
    assert listed["transcript"] == "hello" and listed["duration"] == 4.0 and listed["media_available"]
    data = service.dispatch("history.audio", {"id": item.id})["data_url"]
    assert data == "data:audio/mp4;base64," + base64.b64encode(b"\x00\x01audio").decode()
    with pytest.raises(ControlFailure):
        service.dispatch("history.audio", {"id": "../../etc/passwd"})
    assert service.dispatch("history.delete", {"ids": [item.id, item.id]}) == {"deleted": 1}
    store.record("Kai", "Kai", "incoming", "voice", "bye", None, 24)
    assert service.dispatch("history.clear") == {"deleted": 1}


def test_history_filters_are_validated(service):
    assert call(service, "history.list", {"direction": "generated"})["error"]["code"] == "invalid_params"
    assert call(service, "history.list", {"path": "x"})["error"]["code"] == "invalid_params"
    assert call(service, "history.list", {"limit": 5000})["error"]["code"] == "invalid_params"


def test_link_status_only_shows_a_code_while_waiting(service, paths):
    assert service.dispatch("link.status") == {"state": "idle"}
    linking.write_status(paths, "waiting", expires_at=9e12)
    assert "qr" not in service.dispatch("link.status")  # image not written yet
    linking.qr_path(paths).write_bytes(b"\x89PNG fake")
    assert service.dispatch("link.status")["qr"].startswith("data:image/png;base64,")
    linking.write_status(paths, "waiting", expires_at=1)
    assert service.dispatch("link.status") == {"state": "failed", "reason": "expired"}
    linking.write_status(paths, "linked", account="+15555550100")
    assert service.dispatch("link.status") == {"state": "linked", "account": "+15555550100"}


def test_autostart_needs_the_desktop_app(service, monkeypatch):
    monkeypatch.delenv("SIGNAL_SCRIBE_DESKTOP_EXE", raising=False)
    assert service.dispatch("autostart.get")["available"] is False
    assert call(service, "autostart.set", {"enabled": True})["error"]["code"] == "autostart_unavailable"


def test_diagnostics_never_touch_the_network(service):
    names = [check["name"] for check in service.dispatch("diagnostics.get")["checks"]]
    assert {"Settings", "Signal link", "signal-cli", "Whisper model", "Engine"} <= set(names)


def test_internal_errors_are_generic(service, monkeypatch):
    monkeypatch.setattr(ControlService, "state_get", lambda self: 1 / 0)
    response = call(service, "state.get")
    assert response == {"id": 1, "ok": False, "error": {"code": "internal_error",
                                                         "message": "Control operation failed"}}


def test_saved_defaults_validate(paths):
    config.save(paths.config, config.defaults())
    assert ControlService(paths).dispatch("config.get") == config.defaults()


def test_an_engine_waiting_for_a_link_is_not_an_error(paths):
    from scribe import doctor
    from scribe.status import StatusFile
    StatusFile(paths.status_file).update(state="needs_attention", problem="not_linked", detail="Link first")
    engine = next(check for check in doctor.run(paths) if check.name == "Engine")
    assert engine.status == "warning"
    StatusFile(paths.status_file).update(state="needs_attention", problem="unlinked", detail="Link again")
    engine = next(check for check in doctor.run(paths) if check.name == "Engine")
    assert engine.status == "error"

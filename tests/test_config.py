import json

import pytest

from scribe import config


def test_defaults_are_private_and_valid():
    settings = config.defaults()
    config.validate(settings)
    assert settings["delivery"]["mode"] == "note_to_self"
    assert settings["history"]["retention_hours"] == 0
    assert settings["transcription"]["outgoing"] is True


@pytest.mark.parametrize("patch, field", [
    ({"transcription": {"model": "huge"}}, "transcription.model"),
    ({"transcription": {"language": "english"}}, "transcription.language"),
    ({"transcription": {"max_minutes": 0}}, "transcription.max_minutes"),
    ({"transcription": {"groups": "yes"}}, "transcription.groups"),
    ({"delivery": {"mode": "email"}}, "delivery.mode"),
    ({"history": {"retention_hours": -2}}, "history.retention_hours"),
    ({"history": {"conversation_retention_hours": {"Sam": "forever"}}}, "conversation_retention_hours"),
    ({"desktop": {"theme": "neon"}}, "desktop.theme"),
    ({"schema_version": 2}, "schema_version"),
])
def test_invalid_values_name_the_field(patch, field):
    with pytest.raises(config.ConfigError, match=field.replace(".", r"\.")):
        config.validate(config.merge(config.defaults(), patch))


def test_sanitize_replaces_only_the_bad_setting():
    clean, problems = config.sanitize({"transcription": {"model": "huge", "language": "de"},
                                       "extra": {"kept": True}})
    assert clean["transcription"]["model"] == "auto"
    assert clean["transcription"]["language"] == "de"
    assert clean["extra"] == {"kept": True}
    assert len(problems) == 1


def test_load_never_raises(tmp_path):
    missing, problems = config.load(tmp_path / "config.json")
    assert missing == config.defaults() and problems == []
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    settings, problems = config.load(broken)
    assert settings == config.defaults() and problems


def test_read_strict_rejects_unreadable_files(tmp_path):
    broken = tmp_path / "config.json"
    broken.write_text("[]", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.read_strict(broken)


def test_save_is_validated_and_atomic(tmp_path):
    path = tmp_path / "config.json"
    config.save(path, config.defaults())
    with pytest.raises(config.ConfigError):
        config.save(path, config.merge(config.defaults(), {"delivery": {"mode": "email"}}))
    assert json.loads(path.read_text(encoding="utf-8"))["delivery"]["mode"] == "note_to_self"
    assert not list(tmp_path.glob(".config.json.*"))


def test_patch_replaces_the_retention_override_map():
    current = config.merge(config.defaults(), {"history": {"conversation_retention_hours": {"Sam": 1, "Kai": 2}}})
    merged = config.patch(current, {"history": {"conversation_retention_hours": {"Kai": 24}}})
    assert merged["history"]["conversation_retention_hours"] == {"Kai": 24}
    assert merged["history"]["keep_audio"] is True

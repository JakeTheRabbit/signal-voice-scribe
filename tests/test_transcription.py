import os

import pytest

from scribe import transcription
from scribe.transcription import AudioTooLong, AudioUnreadable, Transcriber, audio_duration, plan

from conftest import FIXTURES

VOICE_NOTE = FIXTURES / "voice-note.m4a"


def test_auto_choices_depend_on_the_gpu():
    assert plan({"model": "auto", "device": "auto", "compute_type": "auto"}, cuda=True) == \
        transcription.Plan("large-v3-turbo", "cuda", "float16")
    assert plan({"model": "auto", "device": "auto", "compute_type": "auto"}, cuda=False) == \
        transcription.Plan("small", "cpu", "int8")
    assert plan({"model": "medium", "device": "cpu", "compute_type": "auto"}) == \
        transcription.Plan("medium", "cpu", "int8")


def test_duration_is_read_without_decoding():
    assert 7.5 < audio_duration(VOICE_NOTE) < 9


def test_garbage_is_unreadable(tmp_path):
    junk = tmp_path / "junk.m4a"
    junk.write_bytes(b"this is not audio" * 100)
    with pytest.raises(AudioUnreadable):
        audio_duration(junk)


def test_too_long_is_refused_before_loading_the_model(tmp_path):
    whisper = Transcriber(tmp_path, {"model": "tiny", "device": "cpu"}, allow_download=False)
    with pytest.raises(AudioTooLong):
        whisper.transcribe(VOICE_NOTE, max_minutes=0.1)
    assert whisper.status["ready"] is False


def test_missing_model_without_download_fails_clearly(tmp_path):
    whisper = Transcriber(tmp_path, {"model": "tiny", "device": "cpu"}, allow_download=False)
    with pytest.raises(RuntimeError, match="not downloaded"):
        whisper.load()


@pytest.mark.skipif(not os.environ.get("SIGNAL_SCRIBE_MODELS"),
                    reason="set SIGNAL_SCRIBE_MODELS to a folder with the tiny.en model to run")
def test_real_transcription_of_the_fixture():
    whisper = Transcriber(os.environ["SIGNAL_SCRIBE_MODELS"], {"model": "tiny.en", "device": "cpu"},
                          allow_download=False)
    result = whisper.transcribe(VOICE_NOTE)
    assert "running about 10 minutes late" in result.text.lower().replace("ten", "10")
    assert result.language == "en"


def test_choosing_the_gpu_explicitly_loads_the_cuda_libraries(tmp_path, monkeypatch):
    """Regression: only the 'auto' path used to make the CUDA libraries findable."""
    import faster_whisper
    prepared = []
    monkeypatch.setattr(transcription, "prepare_cuda_libraries", lambda: prepared.append(True))
    monkeypatch.setattr(transcription, "model_cached", lambda *args: True)
    monkeypatch.setattr(faster_whisper, "WhisperModel", lambda *args, **kwargs: object())
    Transcriber(tmp_path, {"model": "tiny", "device": "cuda", "compute_type": "auto"}).load()
    assert prepared

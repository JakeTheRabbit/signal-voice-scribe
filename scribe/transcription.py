"""On-device speech-to-text with faster-whisper.

Models are downloaded once from Hugging Face into ``models/`` and loaded from
there afterwards without any network access. If the GPU cannot be used (no
NVIDIA card, missing CUDA libraries, out of memory) transcription falls back to
the CPU instead of failing.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .compat import prepare_cuda_libraries

log = logging.getLogger("scribe.whisper")

# Approximate one-time download sizes, shown before downloading.
MODEL_SIZES_MB = {
    "tiny": 75, "tiny.en": 75, "base": 145, "base.en": 145, "small": 484, "small.en": 484,
    "medium": 1530, "medium.en": 1530, "large-v3": 3090, "large-v3-turbo": 1620,
    "distil-large-v3": 1510,
}
CPU_DEFAULT_MODEL = "small"
GPU_DEFAULT_MODEL = "large-v3-turbo"

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# The model download is anonymous on purpose; don't nag about access tokens.
os.environ.setdefault("HF_HUB_VERBOSITY", "error")


class AudioUnreadable(Exception):
    """The file is not audio this computer can decode."""


class AudioTooLong(Exception):
    def __init__(self, minutes: float, limit: int):
        super().__init__(f"{minutes:.0f} min is longer than the {limit} min limit")
        self.minutes = minutes
        self.limit = limit


class Cancelled(Exception):
    """Stopped part-way because the engine is shutting down."""


@dataclass(frozen=True)
class Plan:
    model: str
    device: str
    compute_type: str


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None
    duration: float
    elapsed: float


_cuda: bool | None = None


def _cublas_loadable() -> bool:
    """The GPU is only usable with the CUDA 12 cuBLAS library (the ``cuda`` extra)."""
    import ctypes
    name = "cublas64_12.dll" if os.name == "nt" else "libcublas.so.12"
    try:
        (ctypes.WinDLL if os.name == "nt" else ctypes.CDLL)(name)
        return True
    except OSError:
        return False


def cuda_available() -> bool:
    """True when CTranslate2 can see an NVIDIA GPU and load the CUDA libraries."""
    global _cuda
    if _cuda is None:
        prepare_cuda_libraries()
        try:
            import ctranslate2
            _cuda = ctranslate2.get_cuda_device_count() > 0 and _cublas_loadable()
        except Exception:
            _cuda = False
    return _cuda


def plan(settings: dict, cuda: bool | None = None) -> Plan:
    """Resolve the ``auto`` choices for this computer."""
    device = settings.get("device") or "auto"
    if device == "auto":
        device = "cuda" if (cuda_available() if cuda is None else cuda) else "cpu"
    model = settings.get("model") or "auto"
    if model == "auto":
        model = GPU_DEFAULT_MODEL if device == "cuda" else CPU_DEFAULT_MODEL
    compute = settings.get("compute_type") or "auto"
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return Plan(model, device, compute)


def repo_for(model: str) -> str:
    try:
        from faster_whisper.utils import _MODELS
        return _MODELS.get(model, model)
    except Exception:
        return model


def model_cached(model: str, models_dir: Path) -> bool:
    folder = Path(models_dir) / ("models--" + repo_for(model).replace("/", "--")) / "snapshots"
    return any(folder.glob("*/model.bin"))


def download(model: str, models_dir: Path) -> Path:
    """Fetch a model into ``models_dir`` (network). Returns its folder."""
    from faster_whisper import download_model
    return Path(download_model(model, cache_dir=str(models_dir)))


def cpu_threads() -> int:
    # Half the cores keeps the computer responsive while a long note is transcribed.
    return max(2, min(8, (os.cpu_count() or 4) // 2))


def audio_duration(path: Path) -> float | None:
    """Length in seconds, read from the file header without decoding it."""
    try:
        import av
        with av.open(str(path)) as container:
            if container.duration:
                return container.duration / 1_000_000
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise AudioUnreadable("no audio stream")
            if stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
            return None
    except AudioUnreadable:
        raise
    except Exception as exc:
        raise AudioUnreadable(type(exc).__name__) from exc


class Transcriber:
    def __init__(self, models_dir: Path, settings: dict, allow_download: bool = True):
        self.models_dir = Path(models_dir)
        self.settings = dict(settings)
        self.allow_download = allow_download
        self._model = None
        self._plan: Plan | None = None
        self._lock = threading.RLock()
        self.loading = False
        self.fallback: str | None = None
        self.error: str | None = None

    @property
    def status(self) -> dict:
        planned = self._plan or plan(self.settings)
        return {
            "model": planned.model, "device": planned.device, "compute_type": planned.compute_type,
            "ready": self._model is not None, "loading": self.loading,
            "fallback": self.fallback, "error": self.error,
        }

    def _build(self, chosen: Plan):
        if chosen.device == "cuda":
            prepare_cuda_libraries()  # also when CUDA was chosen explicitly, not via auto
        from faster_whisper import WhisperModel
        common = dict(device=chosen.device, compute_type=chosen.compute_type,
                      download_root=str(self.models_dir), cpu_threads=cpu_threads())
        if model_cached(chosen.model, self.models_dir):
            return WhisperModel(chosen.model, local_files_only=True, **common)
        if not self.allow_download:
            raise RuntimeError(f"Whisper model '{chosen.model}' is not downloaded")
        log.info("downloading Whisper model %s (~%s MB, one time)", chosen.model,
                 MODEL_SIZES_MB.get(chosen.model, "?"))
        return WhisperModel(chosen.model, local_files_only=False, **common)

    def load(self) -> Plan:
        with self._lock:
            if self._model is not None:
                return self._plan
            self.loading = True
            try:
                chosen = plan(self.settings)
                started = time.monotonic()
                try:
                    self._model = self._build(chosen)
                except Exception as exc:
                    if chosen.device != "cuda":
                        self.error = f"Could not load Whisper model {chosen.model}: {type(exc).__name__}"
                        raise
                    chosen = self._cpu_fallback(chosen, exc)
                    self._model = self._build(chosen)
                self._plan = chosen
                self.error = None
                log.info("Whisper %s ready on %s/%s in %.1fs", chosen.model, chosen.device,
                         chosen.compute_type, time.monotonic() - started)
                return chosen
            finally:
                self.loading = False

    def _cpu_fallback(self, failed: Plan, exc: BaseException) -> Plan:
        self.fallback = f"GPU unavailable ({type(exc).__name__}); using the CPU"
        log.warning("Whisper on %s failed (%s: %s); falling back to CPU", failed.device,
                    type(exc).__name__, str(exc)[:200])
        model = CPU_DEFAULT_MODEL if self.settings.get("model", "auto") == "auto" else failed.model
        return Plan(model, "cpu", "int8")

    def transcribe(self, path: Path, max_minutes: int | None = None,
                   should_stop: Callable[[], bool] = lambda: False) -> Transcript:
        duration = audio_duration(path)
        if max_minutes and duration and duration > max_minutes * 60:
            raise AudioTooLong(duration / 60, max_minutes)
        with self._lock:
            self.load()
            try:
                return self._run(path, should_stop)
            except (Cancelled, AudioUnreadable):
                raise
            except Exception as exc:
                if self._plan is None or self._plan.device != "cuda":
                    raise
                # A GPU that loaded fine can still fail mid-run (driver, memory).
                self._model = None
                self._plan = self._cpu_fallback(self._plan, exc)
                self._model = self._build(self._plan)
                return self._run(path, should_stop)

    def _run(self, path: Path, should_stop: Callable[[], bool]) -> Transcript:
        started = time.monotonic()
        language = self.settings.get("language") or None
        options = dict(vad_filter=True, beam_size=5, condition_on_previous_text=False)
        try:
            segments, info = self._model.transcribe(str(path), language=language, **options)
        except ValueError as exc:
            if language is None:
                raise AudioUnreadable(str(exc)[:120]) from exc
            log.warning("language %r was rejected; detecting automatically", language)
            segments, info = self._model.transcribe(str(path), language=None, **options)
        except Exception as exc:
            if type(exc).__module__.startswith("av"):
                raise AudioUnreadable(type(exc).__name__) from exc
            raise
        parts = []
        for segment in segments:
            if should_stop():
                raise Cancelled()
            text = segment.text.strip()
            if text:
                parts.append(text)
        return Transcript(" ".join(parts).strip(), info.language, float(info.duration or 0),
                          time.monotonic() - started)

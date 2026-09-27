"""Operating-system differences in one place (Windows, macOS, Linux)."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .paths import IS_LINUX, IS_MAC, IS_WINDOWS

CREATE_NO_WINDOW = 0x08000000


def hide_console() -> None:
    """Hide this process's console window on Windows, if it has one."""
    if not IS_WINDOWS:
        return
    window = ctypes.windll.kernel32.GetConsoleWindow()
    if window:
        ctypes.windll.user32.ShowWindow(window, 0)  # SW_HIDE


def utf8_streams() -> None:
    """Print Unicode safely even when output is piped through a legacy Windows code page."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def no_window() -> dict:
    """Popen arguments that stop a console window flashing up on Windows."""
    return {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}


def open_path(path: Path | str) -> bool:
    """Open a file or folder with the desktop's default handler."""
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # noqa: S606 - Windows only
        elif IS_MAC:
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _retry(operation, attempts: int = 20):
    """Windows refuses to replace/read a file another process has open for a moment."""
    for attempt in range(attempts):
        try:
            return operation()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05)


def write_json_atomic(path: Path, value, *, indent: int | None = 2) -> None:
    """Write JSON so readers only ever see the old or the new complete file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=indent, ensure_ascii=False, allow_nan=False) + "\n"
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _retry(lambda: os.replace(temp, path))
    finally:
        Path(temp).unlink(missing_ok=True)


def read_json(path: Path, limit: int = 4 * 1024 * 1024):
    """Read a small JSON file; returns None when missing, oversized or invalid."""
    try:
        raw = _retry(lambda: Path(path).read_bytes()[: limit + 1])
    except OSError:
        return None
    if len(raw) > limit:
        return None
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        return None


_dll_handles: list = []
_cuda_prepared: list[Path] | None = None


def prepare_cuda_libraries(site_packages: list[Path] | None = None) -> list[Path]:
    """Make pip-installed NVIDIA CUDA 12 libraries visible to CTranslate2.

    The optional ``cuda`` extra installs cuBLAS and cuDNN as Python packages.
    CTranslate2 loads them by file name, so Windows needs the folders added to
    the DLL search path and Linux needs them preloaded (LD_LIBRARY_PATH is only
    read when a process starts). Safe to call when the packages are absent.
    """
    global _cuda_prepared
    if IS_MAC:
        return []
    if _cuda_prepared is not None and site_packages is None:
        return _cuda_prepared
    roots = site_packages or [Path(p) for p in sys.path if p.endswith("site-packages")]
    found: list[Path] = []
    for root in roots:
        for component in ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime"):
            folder = root / "nvidia" / component / ("bin" if IS_WINDOWS else "lib")
            if folder.is_dir() and folder not in found:
                found.append(folder)
    if IS_WINDOWS:
        for folder in found:
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                _dll_handles.append(os.add_dll_directory(str(folder)))
    elif IS_LINUX:
        # Preloading by full path satisfies CTranslate2's later dlopen by soname.
        # cuDNN finds its own sub-libraries next to itself.
        for pattern in ("libcublasLt.so.1*", "libcublas.so.1*", "libcudnn.so.9*", "libnvrtc.so.1*"):
            for folder in found:
                for library in sorted(folder.glob(pattern))[:1]:
                    try:
                        _dll_handles.append(ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL))
                    except OSError:
                        pass
    if site_packages is None:
        _cuda_prepared = found
    return found

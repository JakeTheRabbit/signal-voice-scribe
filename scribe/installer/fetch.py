"""Downloads that are verified before use, and archives that can't escape their folder."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .. import __version__

USER_AGENT = f"signal-scribe-installer/{__version__}"


class DownloadError(RuntimeError):
    pass


def _open(url: str, timeout: float = 60):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https URLs from pins


def get_json(url: str, attempts: int = 3):
    for attempt in range(attempts):
        try:
            with _open(url) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if attempt == attempts - 1:
                raise DownloadError(f"Could not read {url}: {exc}") from exc
            time.sleep(2 * (attempt + 1))


def get_text(url: str, attempts: int = 3) -> str:
    for attempt in range(attempts):
        try:
            with _open(url) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            if attempt == attempts - 1:
                raise DownloadError(f"Could not read {url}: {exc}") from exc
            time.sleep(2 * (attempt + 1))


def download(url: str, destination: Path, sha256: str | None, label: str, attempts: int = 3) -> Path:
    """Download to ``destination`` and verify its SHA-256 (when one is known)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(attempts):
        digest = hashlib.sha256()
        partial = destination.with_name(destination.name + ".part")
        try:
            with _open(url, timeout=120) as response, open(partial, "wb") as target:
                total = int(response.headers.get("Content-Length") or 0)
                received, shown = 0, -1
                while chunk := response.read(1024 * 256):
                    target.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if total and sys.stderr.isatty():
                        percent = received * 100 // total
                        if percent != shown:
                            shown = percent
                            print(f"\r      {label}: {percent}% of {total / 1024 / 1024:.0f} MB",
                                  end="", file=sys.stderr, flush=True)
            if total and sys.stderr.isatty():
                print(file=sys.stderr)
            if sha256 and digest.hexdigest().lower() != sha256.lower():
                raise DownloadError(f"{label} failed its checksum; the download was discarded")
            partial.replace(destination)
            return destination
        except DownloadError:
            partial.unlink(missing_ok=True)
            raise
        except (urllib.error.URLError, OSError) as exc:
            partial.unlink(missing_ok=True)
            last_error = exc
            time.sleep(3 * (attempt + 1))
    raise DownloadError(f"Could not download {label}: {last_error}")


def extract(archive: Path, destination: Path) -> Path:
    """Extract into a fresh folder and return the single top-level folder inside it."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    name = archive.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive) as tar:
            tar.extractall(destination, filter="data")
    elif name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            root = destination.resolve()
            for member in bundle.infolist():
                target = (destination / member.filename).resolve()
                if root != target and root not in target.parents:
                    raise DownloadError(f"{archive.name} contains an unsafe path")
            bundle.extractall(destination)
    else:
        raise DownloadError(f"Unsupported archive: {archive.name}")
    entries = [entry for entry in destination.iterdir() if not entry.name.startswith(".")]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else destination


def replace_folder(new: Path, final: Path) -> None:
    """Swap ``new`` into ``final`` so a failed update never leaves a half-folder."""
    old = final.with_name(final.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if final.exists():
        final.rename(old)
    try:
        new.rename(final)
    except OSError:
        if old.exists() and not final.exists():
            old.rename(final)
        raise
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)


def temp_dir(parent: Path) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=".download-", dir=parent))

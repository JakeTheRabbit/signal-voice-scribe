"""Where Signal Scribe keeps its code, data and bundled runtime.

The *root* is the folder that contains ``transcriber.py``. Everything the app
writes lives under the *home* folder, which defaults to the root so an install
is self-contained: delete the folder and it is gone. Headless and container
installs can point ``SIGNAL_SCRIBE_HOME`` somewhere else.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


@dataclass(frozen=True)
class Paths:
    root: Path
    home: Path

    @property
    def config(self) -> Path:
        return self.home / "config.json"

    @property
    def data(self) -> Path:
        """signal-cli's ``--config`` folder plus Signal Scribe's own state."""
        return self.home / "data"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def models(self) -> Path:
        return self.home / "models"

    @property
    def runtime(self) -> Path:
        """Java and signal-cli downloaded by the installer."""
        return self.root / "runtime"

    @property
    def attachments(self) -> Path:
        return self.data / "attachments"

    @property
    def status_file(self) -> Path:
        return self.data / "engine-status.json"

    @property
    def jobs_db(self) -> Path:
        return self.data / "jobs.sqlite3"

    @property
    def history_db(self) -> Path:
        return self.data / "history.sqlite3"

    @property
    def history_media(self) -> Path:
        return self.data / "history-media"

    @property
    def link_dir(self) -> Path:
        return self.data / "link"

    def ensure(self) -> "Paths":
        for directory in (self.data, self.logs, self.models):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def resolve(root: Path | str | None = None, home: Path | str | None = None) -> Paths:
    selected_root = Path(root or ROOT).resolve()
    selected_home = home or os.environ.get("SIGNAL_SCRIBE_HOME") or selected_root
    return Paths(selected_root, Path(selected_home).expanduser().resolve())

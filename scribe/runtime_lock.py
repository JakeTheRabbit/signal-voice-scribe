"""One receiver per install: a lock file held for the engine's whole life.

Two engines on the same signal-cli data would fight over the account, so the
engine (and linking) hold ``data/.receiver.lock`` while they run. The desktop
app checks the same file before starting an engine.

* The file is opened read/write, created if needed and never truncated.
* Windows: non-blocking exclusive lock on byte 0, compatible with the desktop's
  LockFileEx probe. Unix: ``flock`` (not POSIX record locks).
* Closing the descriptor (or the process dying) releases the lock. The file is
  never deleted, which avoids races between two processes re-creating it.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path


class ReceiverBusyError(RuntimeError):
    def __init__(self):
        super().__init__("Signal Scribe is already running for this install. Stop it before starting another.")


class ReceiverLease:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir).resolve() / ".receiver.lock"
        self._fd = None

    def acquire(self) -> "ReceiverLease":
        if self._fd is not None:
            raise RuntimeError("Receiver lease already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # os.open descriptors are not inherited, so signal-cli never holds the lock.
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ReceiverBusyError() from None
            raise
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def close(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback):
        self.close()

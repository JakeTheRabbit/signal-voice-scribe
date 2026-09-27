"""Real OS-lock tests; subprocesses only hold fixture leases, never receivers.

ReceiverLease takes the data folder; the lock file is data/.receiver.lock.
"""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from scribe.runtime_lock import ReceiverBusyError, ReceiverLease


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_receiver_lease_is_nonblocking_and_released_on_context_exit(tmp_path):
    with ReceiverLease(tmp_path / "data"):
        with pytest.raises(ReceiverBusyError, match="already running"):
            with ReceiverLease(tmp_path / "data"):
                pytest.fail("second receiver acquired the same lease")
    assert (tmp_path / "data" / ".receiver.lock").is_file()
    with ReceiverLease(tmp_path / "data"):
        pass


def test_receiver_lease_keeps_existing_file_identity_and_contents(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    path = data / ".receiver.lock"
    path.write_bytes(b"fixture marker; not a PID")
    before = path.stat().st_ino
    with ReceiverLease(data):
        pass
    assert path.stat().st_ino == before
    assert path.read_bytes() == b"fixture marker; not a PID"


def test_distinct_roots_do_not_block_each_other(tmp_path):
    with ReceiverLease(tmp_path / "first" / "data"), ReceiverLease(tmp_path / "second" / "data"):
        pass


def test_receiver_lease_releases_on_exception(tmp_path):
    with pytest.raises(RuntimeError, match="fixture failure"):
        with ReceiverLease(tmp_path / "data"):
            raise RuntimeError("fixture failure")
    with ReceiverLease(tmp_path / "data"):
        pass


def test_receiver_lease_cannot_acquire_twice_on_same_object(tmp_path):
    lease = ReceiverLease(tmp_path / "data")
    with lease:
        with pytest.raises(RuntimeError, match="already acquired"):
            lease.acquire()
        with pytest.raises(ReceiverBusyError):
            with ReceiverLease(tmp_path / "data"):
                pass
    lease.close()  # Cleanup is safe even if a caller already exited its context.


def test_invalid_lock_directory_is_not_misreported_as_another_receiver(tmp_path):
    (tmp_path / "data").write_text("not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        with ReceiverLease(tmp_path / "data"):
            pass


@pytest.mark.parametrize("terminate", [False, True])
def test_separate_process_owns_lease_and_os_releases_it_on_exit(tmp_path, terminate):
    script = """
import sys
from scribe.runtime_lock import ReceiverLease
with ReceiverLease(sys.argv[1] + "/data"):
    print('fixture lease ready', flush=True)
    sys.stdin.read(1)
"""
    proc = subprocess.Popen(
        [sys.executable, "-B", "-c", script, str(tmp_path)], cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}),
    )
    try:
        # A bounded thread wait avoids hanging CI if startup regresses.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as executor:
            line = executor.submit(proc.stdout.readline)
            try:
                assert line.result(timeout=15) == "fixture lease ready\n"
            finally:
                if not line.done():
                    proc.kill()
        with pytest.raises(ReceiverBusyError):
            with ReceiverLease(tmp_path / "data"):
                pass
        if terminate:
            proc.kill()
            proc.communicate(timeout=15)
        else:
            _, stderr = proc.communicate("x", timeout=15)
            assert proc.returncode == 0, stderr
        with ReceiverLease(tmp_path / "data"):
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=15)


def test_receiver_lease_interoperates_with_native_lock_range(tmp_path):
    with ReceiverLease(tmp_path / "data"):
        with open(tmp_path / "data" / ".receiver.lock", "r+b", buffering=0) as stream:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                import msvcrt

                class Overlapped(ctypes.Structure):
                    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                                ("hEvent", wintypes.HANDLE)]

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                lock_file = kernel.LockFileEx
                lock_file.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
                lock_file.restype = wintypes.BOOL
                overlap = Overlapped()
                assert not lock_file(msvcrt.get_osfhandle(stream.fileno()), 3, 0, 1, 0, ctypes.byref(overlap))
                assert ctypes.get_last_error() == 33  # ERROR_LOCK_VIOLATION
            else:
                import fcntl
                with pytest.raises(BlockingIOError):
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

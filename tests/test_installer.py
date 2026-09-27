import hashlib
import io
import json
import tarfile
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scribe import __version__, autostart
from scribe.installer import desktop, fetch, runtime
from scribe.installer.fetch import DownloadError
from scribe.paths import Paths


def file_url(path):
    return path.resolve().as_uri()


def test_download_verifies_the_checksum(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"signal scribe")
    good = hashlib.sha256(b"signal scribe").hexdigest()
    target = fetch.download(file_url(source), tmp_path / "out.bin", good, "test")
    assert target.read_bytes() == b"signal scribe"
    with pytest.raises(DownloadError, match="checksum"):
        fetch.download(file_url(source), tmp_path / "bad.bin", "0" * 64, "test")
    assert not (tmp_path / "bad.bin").exists() and not (tmp_path / "bad.bin.part").exists()


def test_tar_extraction_blocks_path_traversal(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        data = b"x"
        info = tarfile.TarInfo("../escaped.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(Exception):
        fetch.extract(archive, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()


def test_zip_extraction_blocks_path_traversal(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.txt", "x")
    with pytest.raises(DownloadError):
        fetch.extract(archive, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_returns_the_single_top_folder(tmp_path):
    archive = tmp_path / "ok.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("signal-cli-1.0/lib/x.jar")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    top = fetch.extract(archive, tmp_path / "out")
    assert top.name == "signal-cli-1.0" and (top / "lib" / "x.jar").exists()


def test_replace_folder_swaps_atomically(tmp_path):
    final = tmp_path / "signal-cli"
    final.mkdir()
    (final / "old").write_text("1")
    new = tmp_path / "staged"
    new.mkdir()
    (new / "new").write_text("2")
    fetch.replace_folder(new, final)
    assert [p.name for p in final.iterdir()] == ["new"]
    assert not (tmp_path / "signal-cli.old").exists()


@pytest.mark.parametrize("system, machine, expected", [
    ("win", "AMD64", ("windows", "x64")),
    ("mac", "arm64", ("mac", "aarch64")),
    ("linux", "x86_64", ("linux", "x64")),
])
def test_platform_names_for_downloads(monkeypatch, system, machine, expected):
    monkeypatch.setattr(runtime, "IS_WINDOWS", system == "win")
    monkeypatch.setattr(runtime, "IS_MAC", system == "mac")
    monkeypatch.setattr(runtime.platform, "machine", lambda: machine)
    monkeypatch.setattr(runtime.platform, "libc_ver", lambda: ("glibc", "2.39"))
    assert runtime.machine() == expected


def test_versions_match_everywhere():
    """The installer downloads the desktop app built for __version__, so every manifest must agree."""
    root = Path(__file__).resolve().parents[1]
    versions = {
        "pyproject.toml": tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"],
        "package.json": json.loads((root / "desktop" / "package.json").read_text("utf-8"))["version"],
        "tauri.conf.json": json.loads(
            (root / "desktop" / "src-tauri" / "tauri.conf.json").read_text("utf-8"))["version"],
        "Cargo.toml": tomllib.loads(
            (root / "desktop" / "src-tauri" / "Cargo.toml").read_text("utf-8"))["package"]["version"],
    }
    assert set(versions.values()) == {__version__}, versions
    assert f"## [{__version__}]" in (root / "CHANGELOG.md").read_text("utf-8")


def test_release_assets_exist_for_supported_platforms(monkeypatch):
    for system, machine, asset in (("win", "AMD64", "signal-scribe-windows-x64.exe"),
                                   ("mac", "arm64", "signal-scribe-macos-universal.app.tar.gz"),
                                   ("linux", "x86_64", "signal-scribe-linux-x64.AppImage"),
                                   ("linux", "aarch64", None)):
        monkeypatch.setattr(desktop, "IS_WINDOWS", system == "win")
        monkeypatch.setattr(desktop, "IS_MAC", system == "mac")
        monkeypatch.setattr(desktop, "IS_LINUX", system == "linux")
        monkeypatch.setattr(runtime, "IS_WINDOWS", system == "win")
        monkeypatch.setattr(runtime, "IS_MAC", system == "mac")
        monkeypatch.setattr(runtime.platform, "machine", lambda m=machine: m)
        assert desktop.asset_name() == asset


def test_freedesktop_exec_quoting():
    command = ["/home/user/Signal Scribe/app/AppRun", "--root", '/home/user/it\'s "here"/$HOME']
    line = autostart.desktop_exec(command)
    assert line.startswith('"/home/user/Signal Scribe/app/AppRun" --root ')
    assert '\\"here\\"' in line and "\\$HOME" in line


def test_linux_autostart_writes_a_desktop_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart, "IS_LINUX", True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    target = autostart.Target(["/opt/app/AppRun", "--hidden"], "desktop", "/opt/app")
    autostart.set_enabled(True, target)
    entry = tmp_path / "autostart" / "signal-scribe.desktop"
    assert "Exec=/opt/app/AppRun --hidden" in entry.read_text()
    assert autostart.is_enabled()
    autostart.set_enabled(False, None)
    assert not entry.exists() and not autostart.is_enabled()


def test_mac_launch_agent(monkeypatch, tmp_path):
    import plistlib
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    monkeypatch.setattr(autostart, "IS_MAC", True)
    monkeypatch.setenv("HOME", str(tmp_path))
    target = autostart.Target(["/Applications/Signal Scribe.app/Contents/MacOS/signal-scribe", "--hidden"],
                              "desktop", "/tmp")
    autostart.set_enabled(True, target)
    agent = tmp_path / "Library" / "LaunchAgents" / f"{autostart.LAUNCH_AGENT}.plist"
    assert plistlib.loads(agent.read_bytes())["ProgramArguments"] == target.command
    autostart.set_enabled(False, None)
    assert not agent.exists()


@pytest.mark.parametrize("text, owner, expected", [
    (r'"C:\Apps\scribe\runtime\desktop\signal-scribe.exe" --root C:\Apps\scribe --hidden', r"C:\Apps\scribe", True),
    (r'"C:\Apps\scribe-2\runtime\desktop\signal-scribe.exe" --root C:\Apps\scribe-2', r"C:\Apps\scribe", False),
    ('/home/user/signal scribe/app/AppRun --root "/home/user/signal scribe"', "/home/user/signal scribe", True),
    (r"pythonw.exe C:\Github\signal-scribe\app.py", r"C:\Github\signal-voice-scribe", False),
    (None, "/opt/scribe", False),
])
def test_entries_are_matched_to_their_own_install(text, owner, expected):
    assert autostart.points_to(text, owner) is expected


def test_switching_between_desktop_and_headless_keeps_one_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart, "IS_LINUX", True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(autostart.shutil, "which", lambda name: "/usr/bin/systemctl")
    calls = []
    monkeypatch.setattr(autostart.subprocess, "run", lambda args, **kwargs: calls.append(args[1:]))
    entry = tmp_path / "autostart" / "signal-scribe.desktop"
    unit = tmp_path / "systemd" / "user" / autostart.SYSTEMD_UNIT
    engine = autostart.Target(["/opt/app/.venv/bin/python", "/opt/app/transcriber.py"], "engine", "/opt/app")
    window = autostart.Target(["/opt/app/runtime/desktop/app/AppRun", "--root", "/opt/app", "--hidden"],
                              "desktop", "/opt/app")
    autostart.set_enabled(True, engine)
    assert unit.exists() and not entry.exists()
    autostart.set_enabled(True, window)
    assert entry.exists() and not unit.exists()
    assert ["--user", "disable", "--now", autostart.SYSTEMD_UNIT] in calls
    autostart.set_enabled(True, engine)
    assert unit.exists() and not entry.exists()


def test_missing_linux_libraries_are_listed(monkeypatch, tmp_path):
    paths = Paths(tmp_path, tmp_path)
    monkeypatch.setattr(desktop, "IS_WINDOWS", False)
    monkeypatch.setattr(desktop, "IS_MAC", False)
    monkeypatch.setattr(desktop, "IS_LINUX", True)
    binary = desktop.app_location(paths) / "usr" / "bin" / "signal-scribe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x7fELF")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/ldd")
    seen = {}

    def fake_ldd(args, env, **kwargs):
        seen["library_path"] = env["LD_LIBRARY_PATH"]
        return SimpleNamespace(stdout="\tlinux-vdso.so.1 (0x00007ffd)\n"
                                      "\tlibgtk-3.so.0 => /opt/app/usr/lib/libgtk-3.so.0 (0x7f00)\n"
                                      "\tlibgbm.so.1 => not found\n\tlibEGL.so.1 => not found\n"
                                      "\tlibEGL.so.1 => not found\n")
    monkeypatch.setattr(desktop.subprocess, "run", fake_ldd)
    monkeypatch.setattr(desktop.ctypes, "CDLL", lambda name: None)
    assert desktop.missing_libraries(paths) == ["libEGL.so.1", "libgbm.so.1"]
    assert seen["library_path"] == str(desktop.app_location(paths) / "usr" / "lib")

    def no_library(name):
        raise OSError(name)
    monkeypatch.setattr(desktop.ctypes, "CDLL", no_library)
    assert "libGLESv2.so.2" in desktop.missing_libraries(paths)
    monkeypatch.setattr(desktop, "IS_LINUX", False)
    assert desktop.missing_libraries(paths) == []


def test_disabling_leaves_another_installs_entry_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart, "IS_LINUX", True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    other = autostart.Target(["/opt/other/app/AppRun", "--root", "/opt/other", "--hidden"], "desktop", "/opt/other")
    autostart.set_enabled(True, other)
    autostart.set_enabled(False, None, owner="/opt/mine")
    assert autostart.is_enabled("/opt/other") and not autostart.is_enabled("/opt/mine")
    autostart.set_enabled(False, None, owner="/opt/other")
    assert not autostart.is_enabled()

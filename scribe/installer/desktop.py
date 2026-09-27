"""The desktop app (window + tray): download the matching release build and add launchers."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from .. import __version__
from ..paths import IS_LINUX, IS_MAC, IS_WINDOWS, Paths
from . import pins
from .fetch import DownloadError, download, extract, get_text, replace_folder, temp_dir
from .runtime import machine

APP_NAME = "Signal Scribe"


def asset_name() -> str | None:
    """The release file for this computer, or None if there is no prebuilt app."""
    _, arch = machine()
    if IS_WINDOWS and arch == "x64":
        return "signal-scribe-windows-x64.exe"
    if IS_MAC:
        return "signal-scribe-macos-universal.app.tar.gz"
    if IS_LINUX and arch == "x64":
        return "signal-scribe-linux-x64.AppImage"
    return None


def pointer_file() -> Path:
    """Where the app looks up its install folder when it can't find it nearby."""
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "signal-scribe" / "root.txt"


def app_location(paths: Paths) -> Path:
    if IS_MAC:
        return Path.home() / "Applications" / f"{APP_NAME}.app"
    if IS_WINDOWS:
        return paths.runtime / "desktop" / "signal-scribe.exe"
    return paths.runtime / "desktop" / "app"  # the unpacked AppImage


def executable(paths: Paths) -> Path:
    """The program to start (inside the bundle on macOS)."""
    location = app_location(paths)
    if IS_MAC:
        return location / "Contents" / "MacOS" / "signal-scribe"
    if IS_LINUX:
        return location / "AppRun" if (location / "AppRun").exists() else location / "signal-scribe"
    return location


def launch_command(paths: Paths, hidden: bool = False) -> list[str]:
    command = [str(executable(paths)), "--root", str(paths.root)]
    return command + ["--hidden"] if hidden else command


def install_file(source: Path, paths: Paths) -> Path:
    """Install a desktop build (a downloaded asset or a local build)."""
    target = app_location(paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    if IS_MAC:
        if source.is_dir():
            work = temp_dir(paths.runtime)
            staged = work / f"{APP_NAME}.app"
            shutil.copytree(source, staged, symlinks=True)
        else:
            work = temp_dir(paths.runtime)
            staged = extract(source, work / "unpacked")
            if staged.suffix != ".app":
                staged = next(staged.glob("*.app"), staged)
        try:
            replace_folder(staged, target)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    elif IS_LINUX:
        # Unpack the AppImage once: no FUSE needed and no unpacking on every start.
        work = temp_dir(paths.runtime)
        try:
            staged = work / "app"
            if source.is_dir():
                shutil.copytree(source, staged, symlinks=True)
            elif source.suffix == ".AppImage":
                runnable = work / source.name
                shutil.copy2(source, runnable)
                runnable.chmod(0o755)
                subprocess.run([str(runnable), "--appimage-extract"], cwd=work, check=True,
                               capture_output=True)
                (work / "squashfs-root").rename(staged)
            else:  # a plain binary built from source
                staged.mkdir()
                shutil.copy2(source, staged / "signal-scribe")
                (staged / "signal-scribe").chmod(0o755)
            replace_folder(staged, target)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    else:
        temporary = target.with_name(target.name + ".new")
        shutil.copy2(source, temporary)
        temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(temporary, target)
    pointer = pointer_file()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(paths.root), encoding="utf-8")
    return executable(paths)


def download_release(paths: Paths, say, version: str = __version__) -> Path:
    name = asset_name()
    if name is None:
        raise DownloadError("There is no prebuilt desktop app for this computer")
    base = f"{pins.RELEASES}/download/v{version}/"
    sums = {}
    for line in get_text(base + "SHA256SUMS.txt").splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0]
    if name not in sums:
        raise DownloadError(f"Release v{version} has no {name}")
    say(f"Downloading the desktop app ({name})")
    work = temp_dir(paths.runtime)
    try:
        return install_file(download(base + name, work / name, sums[name], "Desktop app"), paths)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_from_source(paths: Paths, say) -> Path:
    """Build with Rust and pnpm (for development, or platforms without a release build)."""
    desktop = paths.root / "desktop"
    pnpm = shutil.which("pnpm")
    if not pnpm or not shutil.which("cargo"):
        raise DownloadError("Building the desktop app needs Rust (cargo) and pnpm")
    say("Building the desktop app from source (this takes a few minutes)")
    subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=desktop, check=True)
    subprocess.run([pnpm, "tauri", "build", "--bundles", "app"] if IS_MAC else
                   [pnpm, "tauri", "build", "--no-bundle"], cwd=desktop, check=True)
    release = desktop / "src-tauri" / "target" / "release"
    built = (release / "bundle" / "macos" / f"{APP_NAME}.app" if IS_MAC
             else release / ("signal-scribe.exe" if IS_WINDOWS else "signal-scribe"))
    return install_file(built, paths)


# --- launchers ------------------------------------------------------------------------------

def _powershell_shortcut(link: Path, target: str, arguments: str, workdir: str, icon: str) -> None:
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SS_LINK);"
        "$s.TargetPath=$env:SS_TARGET;$s.Arguments=$env:SS_ARGS;$s.WorkingDirectory=$env:SS_DIR;"
        "$s.IconLocation=$env:SS_ICON;$s.Description='Read your Signal voice notes';$s.Save()")
    environment = {**os.environ, "SS_LINK": str(link), "SS_TARGET": target, "SS_ARGS": arguments,
                   "SS_DIR": workdir, "SS_ICON": icon}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   env=environment, check=True, capture_output=True, creationflags=0x08000000)


def windows_shortcut_folders(desktop_icon: bool) -> list[Path]:
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    folders = [appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
    if desktop_icon:
        folders.append(Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop")
    return folders


def linux_entry() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "applications" / "signal-scribe.desktop"


def add_launchers(paths: Paths, desktop_icon: bool = True) -> list[Path]:
    """Start Menu / desktop shortcuts on Windows, an app-menu entry on Linux."""
    exe = executable(paths)
    created: list[Path] = []
    if IS_WINDOWS:
        for folder in windows_shortcut_folders(desktop_icon):
            if folder.is_dir():
                link = folder / f"{APP_NAME}.lnk"
                _powershell_shortcut(link, str(exe), subprocess.list2cmdline(["--root", str(paths.root)]),
                                     str(paths.root), f"{exe},0")
                created.append(link)
    elif IS_LINUX:
        from ...autostart import desktop_exec
        entry = linux_entry()
        entry.parent.mkdir(parents=True, exist_ok=True)
        command = launch_command(paths)
        entry.write_text(
            "[Desktop Entry]\nType=Application\nName=Signal Scribe\n"
            "Comment=Read your Signal voice notes instead of listening to them\n"
            f"Exec={desktop_exec(command)}\nIcon={paths.root / 'assets' / 'icon.png'}\n"
            "Terminal=false\nCategories=Network;InstantMessaging;Utility;\nStartupWMClass=signal-scribe\n",
            encoding="utf-8")
        created.append(entry)
    return created


def remove_launchers(paths: Paths) -> None:
    if IS_WINDOWS:
        for folder in windows_shortcut_folders(True):
            (folder / f"{APP_NAME}.lnk").unlink(missing_ok=True)
    elif IS_LINUX:
        linux_entry().unlink(missing_ok=True)
    pointer_file().unlink(missing_ok=True)

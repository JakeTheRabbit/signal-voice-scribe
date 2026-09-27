"""Java and signal-cli, downloaded into ``runtime/`` inside the install folder."""
from __future__ import annotations

import platform
import shutil
from pathlib import Path

from ..compat import read_json, write_json_atomic
from ..paths import IS_LINUX, IS_MAC, IS_WINDOWS, Paths
from ..signal_cli import find_java, java_version, signal_cli_home, signal_cli_version
from . import pins
from .fetch import DownloadError, download, extract, get_json, replace_folder, temp_dir


def machine() -> tuple[str, str]:
    """(Adoptium OS name, Adoptium architecture) for this computer."""
    arch = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "aarch64", "aarch64": "aarch64"}.get(arch, arch)
    if IS_WINDOWS:
        return "windows", arch
    if IS_MAC:
        return "mac", arch
    libc = platform.libc_ver()[0]
    return ("linux" if libc in ("glibc", "") else "alpine-linux"), arch


def ensure_java(paths: Paths, say) -> Path:
    found = find_java(paths, pins.JAVA_MAJOR)
    if found:
        say(f"Java {java_version(found)} found")
        return found
    os_name, arch = machine()
    say(f"Downloading Java {pins.JAVA_MAJOR} (Eclipse Temurin JRE for {os_name}/{arch})")
    releases = get_json(pins.ADOPTIUM_API.format(major=pins.JAVA_MAJOR, arch=arch, os=os_name))
    if not releases:
        raise DownloadError(f"No Java {pins.JAVA_MAJOR} runtime is published for {os_name}/{arch}. "
                            "Install Java yourself and set SIGNAL_SCRIBE_JAVA to its java executable.")
    package = releases[0]["binary"]["package"]
    work = temp_dir(paths.runtime)
    try:
        archive = download(package["link"], work / package["name"], package["checksum"], "Java")
        top = extract(archive, work / "unpacked")
        replace_folder(top, paths.runtime / "jre")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    found = find_java(paths, pins.JAVA_MAJOR)
    if not found:
        raise DownloadError("Java was downloaded but does not run on this computer")
    say(f"Java {java_version(found)} installed")
    return found


def ensure_signal_cli(paths: Paths, say) -> None:
    home = signal_cli_home(paths)
    if signal_cli_version(paths) == pins.SIGNAL_CLI_VERSION and any((home / "lib").glob("*.jar")):
        say(f"signal-cli {pins.SIGNAL_CLI_VERSION} already installed")
        return
    say(f"Downloading signal-cli {pins.SIGNAL_CLI_VERSION} (about 120 MB, checksum-verified)")
    work = temp_dir(paths.runtime)
    try:
        archive = download(pins.SIGNAL_CLI_URL, work / "signal-cli.tar.gz", pins.SIGNAL_CLI_SHA256, "signal-cli")
        top = extract(archive, work / "unpacked")
        if not any((top / "lib").glob("*.jar")):
            raise DownloadError("The signal-cli download did not contain its program files")
        write_json_atomic(top / "signal-scribe.json", {"version": pins.SIGNAL_CLI_VERSION})
        replace_folder(top, home)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    say(f"signal-cli {pins.SIGNAL_CLI_VERSION} installed")
    _, arch = machine()
    if IS_LINUX and arch != "x64":
        say("NOTE: signal-cli ships its Signal protocol library for x86-64 only. On this "
            f"{arch} computer, see https://github.com/AsamK/signal-cli/wiki/Provide-native-lib-for-libsignal")


def installed_versions(paths: Paths) -> dict:
    marker = read_json(signal_cli_home(paths) / "signal-scribe.json")
    return {"signal_cli": marker.get("version") if isinstance(marker, dict) else None}

"""Start at login: the desktop app (in the tray) or, on servers, the headless engine."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .paths import IS_LINUX, IS_MAC, IS_WINDOWS, Paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "SignalScribe"
LAUNCH_AGENT = "io.github.jaketherabbit.signalscribe"
SYSTEMD_UNIT = "signal-scribe.service"


@dataclass(frozen=True)
class Target:
    command: list[str]
    kind: str  # "desktop" or "engine"
    workdir: str


def desktop_target() -> Target | None:
    """The desktop app passes its own path and runtime folder to the control server."""
    exe, root = os.environ.get("SIGNAL_SCRIBE_DESKTOP_EXE"), os.environ.get("SIGNAL_SCRIBE_DESKTOP_ROOT")
    if not exe or not root or not Path(exe).is_file():
        return None
    return Target([exe, "--root", root, "--hidden"], "desktop", root)


def engine_target(paths: Paths) -> Target:
    """The engine without a window, for computers that run Signal Scribe headless."""
    python = paths.root / ".venv" / ("Scripts/pythonw.exe" if IS_WINDOWS else "bin/python")
    return Target([str(python), str(paths.root / "transcriber.py")], "engine", str(paths.root))


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def _launch_agent() -> Path:
    return _home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT}.plist"


def _xdg_autostart() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")
    return base / "autostart" / "signal-scribe.desktop"


def _systemd_unit() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")
    return base / "systemd" / "user" / SYSTEMD_UNIT


def desktop_exec(command: list[str]) -> str:
    """Quote arguments for a freedesktop ``Exec=`` line."""
    def quote(argument: str) -> str:
        if not any(ch in argument for ch in ' \t"\'\\$`<>|&;()*?#~'):
            return argument
        escaped = argument.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        return f'"{escaped}"'
    return " ".join(quote(part) for part in command)


def windows_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def is_enabled() -> bool:
    if IS_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, RUN_VALUE)
            return True
        except OSError:
            return False
    if IS_MAC:
        return _launch_agent().exists()
    return _xdg_autostart().exists() or _systemd_unit().exists()


def set_enabled(enabled: bool, target: Target | None) -> None:
    if IS_WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled and target:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, windows_command(target.command))
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except OSError:
                    pass
        return
    if IS_MAC:
        agent = _launch_agent()
        if not enabled or not target:
            agent.unlink(missing_ok=True)
            return
        agent.parent.mkdir(parents=True, exist_ok=True)
        plist = {"Label": LAUNCH_AGENT, "ProgramArguments": target.command, "RunAtLoad": True,
                 "WorkingDirectory": target.workdir, "ProcessType": "Interactive"}
        if target.kind == "engine":
            plist["KeepAlive"] = {"SuccessfulExit": False}
            plist["StandardErrorPath"] = str(Path(target.workdir) / "logs" / "launchd.log")
        with open(agent, "wb") as handle:
            plistlib.dump(plist, handle)
        return
    if IS_LINUX:
        _set_linux(enabled, target)


def _set_linux(enabled: bool, target: Target | None) -> None:
    entry, unit = _xdg_autostart(), _systemd_unit()
    systemctl = shutil.which("systemctl")
    if not enabled or not target:
        entry.unlink(missing_ok=True)
        if unit.exists():
            if systemctl:
                subprocess.run([systemctl, "--user", "disable", "--now", SYSTEMD_UNIT], capture_output=True)
            unit.unlink(missing_ok=True)
        return
    if target.kind == "engine" and systemctl:
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(
            "[Unit]\nDescription=Signal Scribe (voice note transcription)\n"
            "After=network-online.target\nWants=network-online.target\n\n"
            f"[Service]\nWorkingDirectory={target.workdir}\n"
            f"ExecStart={desktop_exec(target.command)}\n"
            "Restart=on-failure\nRestartSec=30\n\n[Install]\nWantedBy=default.target\n",
            encoding="utf-8")
        subprocess.run([systemctl, "--user", "daemon-reload"], capture_output=True)
        subprocess.run([systemctl, "--user", "enable", "--now", SYSTEMD_UNIT], capture_output=True)
        return
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Signal Scribe\n"
        f"Exec={desktop_exec(target.command)}\nPath={target.workdir}\n"
        "Terminal=false\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n", encoding="utf-8")

"""``python -m scribe.installer``: everything after the Python environment exists.

install.ps1 and install.sh create the Python environment with uv, then run
this. It is safe to run again: finished steps are skipped and your settings,
Signal link and history are kept.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import traceback
from pathlib import Path

from .. import __version__
from ..compat import utf8_streams
from ..autostart import Target, engine_target, set_enabled
from ..paths import IS_MAC, IS_WINDOWS, resolve
from ..signal_cli import linked_accounts
from ..transcription import MODEL_SIZES_MB, download as download_model, model_cached, plan
from .. import config as settings_module, doctor
from . import desktop
from .fetch import DownloadError
from .runtime import ensure_java, ensure_signal_cli


def step(number: int, total: int, title: str) -> None:
    print(f"\n[{number}/{total}] {title}", flush=True)


def say(message: str) -> None:
    print(f"      {message}", flush=True)


def parse(argv):
    parser = argparse.ArgumentParser(prog="python -m scribe.installer")
    parser.add_argument("--headless", action="store_true",
                        help="no desktop app: run the engine as a background service (servers)")
    parser.add_argument("--desktop", default="download",
                        help="download (default), build (from source), skip, or a path to a local build")
    parser.add_argument("--model", default="auto", help="Whisper model to download now, or 'none'")
    parser.add_argument("--no-autostart", action="store_true", help="don't start at login")
    parser.add_argument("--no-shortcuts", action="store_true", help="don't add menu/desktop shortcuts")
    parser.add_argument("--no-desktop-icon", action="store_true", help="Windows: no desktop shortcut")
    parser.add_argument("--no-launch", action="store_true", help="don't open the app when finished")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    utf8_streams()
    args = parse(argv)
    paths = resolve().ensure()
    total = 6
    print(f"Signal Scribe {__version__} — installing into {paths.root}")
    try:
        step(1, total, "Java")
        ensure_java(paths, say)

        step(2, total, "signal-cli (talks to Signal as a linked device)")
        ensure_signal_cli(paths, say)

        step(3, total, "Settings")
        if paths.config.exists():
            config = settings_module.read_strict(paths.config)
            say("Keeping your existing settings")
        else:
            config = settings_module.save(paths.config, settings_module.defaults())
            say("Created default settings (voice notes → private Note to Self)")

        step(4, total, "Whisper speech model")
        if args.model == "none":
            say("Skipped; it downloads when the first voice note arrives")
        else:
            settings = dict(config["transcription"])
            if args.model != "auto" and settings.get("model") != args.model:
                settings["model"] = args.model
                config = settings_module.save(paths.config, settings_module.patch(config, {"transcription": settings}))
                say(f"Using the {args.model} model from now on")
            chosen = plan(settings)
            if model_cached(chosen.model, paths.models):
                say(f"{chosen.model} already downloaded ({chosen.device.upper()})")
            else:
                say(f"Downloading {chosen.model} for {chosen.device.upper()} "
                    f"(~{MODEL_SIZES_MB.get(chosen.model, '?')} MB, one time)")
                download_model(chosen.model, paths.models)
                say("Done")

        step(5, total, "App and start at login")
        launch: list[str] | None = None
        if args.headless or args.desktop == "skip":
            target = engine_target(paths)
            say("Headless mode: no window; the engine runs in the background")
        else:
            try:
                if args.desktop == "download":
                    exe = desktop.download_release(paths, say)
                elif args.desktop == "build":
                    exe = desktop.build_from_source(paths, say)
                else:
                    exe = desktop.install_file(Path(args.desktop).resolve(), paths)
                say(f"Desktop app installed: {exe}")
                if not args.no_shortcuts:
                    for link in desktop.add_launchers(paths, desktop_icon=not args.no_desktop_icon):
                        say(f"Shortcut: {link}")
                target = Target(desktop.launch_command(paths, hidden=True), "desktop", str(paths.root))
                launch = desktop.launch_command(paths)
            except (DownloadError, OSError, subprocess.CalledProcessError) as exc:
                say(f"The desktop app could not be installed ({exc}).")
                say("Continuing in headless mode. Re-run with --desktop build to build it from source.")
                target = engine_target(paths)
        if args.no_autostart:
            say("Start at login: off")
        else:
            set_enabled(True, target)
            say("Start at login: on (change it any time in the app or by re-running with --no-autostart)")

        step(6, total, "Checking the install")
        checks = doctor.run(paths)
        installed = ("Java", "signal-cli", "Whisper model", "Settings")
        for check in checks:
            if check.name in installed + ("Signal link",):
                label = {"ok": "OK  ", "warning": "WARN", "error": "FAIL"}.get(check.status, check.status)
                say(f"[{label}] {check.name}: {check.detail}")
        # Only what the installer installs can fail it; linking and the engine come later.
        if any(check.status == "error" for check in checks if check.name in installed):
            print("\nSome checks failed. See the messages above, then run the installer again.")
            return 1
    except KeyboardInterrupt:
        print("\nCancelled. Run the installer again to finish; completed steps are kept.")
        return 130
    except (DownloadError, OSError, subprocess.CalledProcessError) as exc:
        print(f"\nInstallation stopped: {exc}", file=sys.stderr)
        print("Check your internet connection and run the installer again. Completed steps are kept.",
              file=sys.stderr)
        return 1
    except Exception:
        traceback.print_exc()
        print("\nUnexpected error. Please report it with the text above.", file=sys.stderr)
        return 1

    linked = bool(linked_accounts(paths))
    print("\nSignal Scribe is installed.")
    if launch and not args.no_launch:
        start_detached(launch, paths.root)
        print("The app is opening." + ("" if linked else " Click “Link Signal” and scan the QR code with your phone."))
    elif launch:
        print("Open “Signal Scribe” from your applications menu.")
    else:
        cli = paths.root / ("signal-scribe.cmd" if IS_WINDOWS else "signal-scribe")
        if not linked:
            print(f"Next: link your Signal account:  {cli} link")
        print(f"Run it now in this terminal:        {cli} run")
    return 0


def start_detached(command: list[str], workdir: Path) -> None:
    kwargs = {"cwd": str(workdir), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    if IS_MAC and ".app/Contents/MacOS/" in command[0]:
        bundle = command[0].split("/Contents/MacOS/")[0]
        command = ["open", bundle, "--args", *command[1:]]
    subprocess.Popen(command, **kwargs)


if __name__ == "__main__":
    sys.exit(main())

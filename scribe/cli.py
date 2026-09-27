"""``signal-scribe`` command line: link, run headless, check and test the install."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, config as settings_module, doctor, linking, status as engine_status
from .compat import utf8_streams
from .paths import resolve
from .signal_cli import linked_accounts

SYMBOLS = {"ok": "OK  ", "warning": "WARN", "error": "FAIL"}


def _paths(args):
    return resolve(home=args.home).ensure()


def cmd_link(args) -> int:
    paths = _paths(args)
    if linked_accounts(paths) and not args.force:
        accounts = linked_accounts(paths)
        if all(a.registered for a in accounts):
            print(f"Already linked to {accounts[0].label}. Use --force to link again.")
            return 0
    print("Starting signal-cli…")

    def show(uri: str) -> None:
        print("\nOn your phone: Signal → Settings → Linked devices → Link new device, then scan:\n")
        linking.print_qr(uri)
        print(f"\nThe code is also saved as an image: {linking.qr_path(paths)}")
        print("Waiting for your phone (the code expires in a few minutes)…")

    code = linking.run(paths, on_uri=show)
    status = linking.read_status(paths)
    if code == 0:
        print(f"\nLinked to {status.get('account') or 'your account'}. Start the engine with: signal-scribe run")
    elif status.get("reason") == "engine_running":
        print("Stop Signal Scribe first (it is running), then link again.", file=sys.stderr)
    else:
        print(f"\nLinking did not finish ({status.get('reason', 'failed')}). Try again.", file=sys.stderr)
    return code


def cmd_run(args) -> int:
    from . import engine
    return engine.main(console=True)


def cmd_status(args) -> int:
    paths = _paths(args)
    accounts = linked_accounts(paths)
    if not accounts:
        print("Signal:  not linked (run: signal-scribe link)")
    else:
        for account in accounts:
            state = "linked" if account.registered else "REMOVED on your phone - link again"
            print(f"Signal:  {account.label} ({state})")
    heartbeat = engine_status.read(paths.status_file)
    if heartbeat is None or heartbeat.get("stale"):
        print("Engine:  not running")
    else:
        print(f"Engine:  {heartbeat.get('detail') or heartbeat.get('state')}")
        model = heartbeat.get("model") or {}
        print(f"Whisper: {model.get('model')} on {str(model.get('device')).upper()}"
              f"{' (ready)' if model.get('ready') else ''}")
        queue = heartbeat.get("queue") or {}
        today = queue.get("today") or {}
        print(f"Queue:   {queue.get('pending', 0)} waiting · today {today.get('done', 0)} done, "
              f"{today.get('failed', 0)} failed")
    return 0


def cmd_doctor(args) -> int:
    paths = _paths(args)
    checks = doctor.run(paths)
    if args.json:
        print(json.dumps(doctor.as_dicts(checks), indent=2))
    else:
        for check in checks:
            print(f"[{SYMBOLS.get(check.status, check.status)}] {check.name}: {check.detail}")
    return 1 if any(check.status == "error" for check in checks) else 0


def cmd_transcribe(args) -> int:
    from .transcription import Transcriber, plan
    paths = _paths(args)
    config, _ = settings_module.load(paths.config)
    settings = dict(config["transcription"])
    for key in ("model", "device", "language"):
        if getattr(args, key):
            settings[key] = getattr(args, key)
    chosen = plan(settings)
    print(f"Transcribing with Whisper {chosen.model} on {chosen.device.upper()}… (nothing is sent anywhere)",
          file=sys.stderr)
    transcriber = Transcriber(paths.models, settings)
    started = time.monotonic()
    result = transcriber.transcribe(Path(args.file))
    if transcriber.fallback:
        print(f"Note: {transcriber.fallback}", file=sys.stderr)
    print(result.text or "(no speech detected)")
    print(f"[{result.duration:.1f}s of audio, language {result.language}, "
          f"{time.monotonic() - started:.1f}s including model load]", file=sys.stderr)
    return 0


def cmd_download_model(args) -> int:
    from .transcription import MODEL_SIZES_MB, download, model_cached, plan
    paths = _paths(args)
    config, _ = settings_module.load(paths.config)
    settings = dict(config["transcription"])
    if args.model:
        settings["model"] = args.model
    model = plan(settings).model
    if model_cached(model, paths.models):
        print(f"Whisper model {model} is already downloaded.")
        return 0
    print(f"Downloading Whisper model {model} (~{MODEL_SIZES_MB.get(model, '?')} MB, one time)…")
    download(model, paths.models)
    print("Done.")
    return 0


def _get(config: dict, dotted: str):
    value = config
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return value


def cmd_config(args) -> int:
    paths = _paths(args)
    config = settings_module.read_strict(paths.config)
    if args.key is None:
        print(json.dumps(config, indent=2))
        return 0
    try:
        current = _get(config, args.key)
    except KeyError:
        print(f"Unknown setting: {args.key}", file=sys.stderr)
        return 2
    if args.value is None:
        print(json.dumps(current))
        return 0
    try:
        value = json.loads(args.value)  # true, false, null and numbers
    except ValueError:
        value = args.value  # plain words such as: small, chat, de
    section, _, key = args.key.rpartition(".")
    update = {key: value}
    for part in reversed(section.split(".") if section else []):
        update = {part: update}
    try:
        settings_module.save(paths.config, settings_module.patch(config, update))
    except settings_module.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"{args.key} = {json.dumps(value)} (restart the engine to apply)")
    return 0


def cmd_unlink(args) -> int:
    paths = _paths(args)
    if not linked_accounts(paths):
        print("This computer is not linked.")
        return 0
    print("1. On your phone: Signal → Settings → Linked devices → tap Signal Scribe → Unlink.")
    print("2. This deletes this computer's Signal keys and message state (not your transcript history).")
    if not args.yes and input("Delete the local Signal keys now? Type 'delete' to confirm: ").strip() != "delete":
        print("Cancelled.")
        return 1
    code = linking.forget(paths)
    if code == 3:
        print("Stop Signal Scribe first, then try again.", file=sys.stderr)
    elif code == 0:
        print("Done. Link again any time with: signal-scribe link")
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signal-scribe",
        description="Read your Signal voice notes instead of listening to them. Everything runs on this computer.")
    parser.add_argument("--home", help="data folder (default: the install folder, or $SIGNAL_SCRIBE_HOME)")
    parser.add_argument("--version", action="version", version=f"Signal Scribe {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    link = commands.add_parser("link", help="link this computer to your Signal account (shows a QR code)")
    link.add_argument("--force", action="store_true", help="link again even if already linked")
    link.set_defaults(func=cmd_link)
    commands.add_parser("run", help="run the engine in this terminal (Ctrl+C stops it)").set_defaults(func=cmd_run)
    commands.add_parser("status", help="show the link and engine status").set_defaults(func=cmd_status)
    check = commands.add_parser("doctor", help="check Java, signal-cli, Whisper and settings")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_doctor)
    test = commands.add_parser("transcribe", help="transcribe an audio file here (tests your setup; sends nothing)")
    test.add_argument("file")
    test.add_argument("--model")
    test.add_argument("--device", choices=settings_module.DEVICES)
    test.add_argument("--language")
    test.set_defaults(func=cmd_transcribe)
    download = commands.add_parser("download-model", help="download the Whisper model now instead of on first use")
    download.add_argument("model", nargs="?", choices=settings_module.MODELS)
    download.set_defaults(func=cmd_download_model)
    configure = commands.add_parser("config", help="show or change a setting, e.g. config delivery.mode chat")
    configure.add_argument("key", nargs="?")
    configure.add_argument("value", nargs="?")
    configure.set_defaults(func=cmd_config)
    unlink = commands.add_parser("unlink", help="forget this computer's Signal keys")
    unlink.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    unlink.set_defaults(func=cmd_unlink)
    return parser


def main(argv: list[str] | None = None) -> int:
    utf8_streams()  # QR codes and names need UTF-8, even through Windows pipes
    args = build_parser().parse_args(argv)
    if args.home:
        import os
        os.environ["SIGNAL_SCRIBE_HOME"] = args.home
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

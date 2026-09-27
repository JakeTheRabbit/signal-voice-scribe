"""``python -m scribe.installer.uninstall``: remove start-at-login, shortcuts and the desktop app.

Your Signal link, settings, history and the downloaded model stay in the
install folder unless ``--purge`` is given, which deletes the whole folder's
generated contents. Either way, also remove "Signal Scribe" from your phone's
Signal → Settings → Linked devices.
"""
from __future__ import annotations

import argparse
import shutil
import sys

from ..compat import utf8_streams
from ..autostart import set_enabled
from ..paths import IS_MAC, resolve
from . import desktop

GENERATED = ("data", "logs", "models", "config.json", "runtime", ".venv")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scribe.installer.uninstall")
    parser.add_argument("--purge", action="store_true",
                        help="also delete your Signal link, settings, history, models and the runtime")
    parser.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    utf8_streams()
    args = parser.parse_args(argv)
    paths = resolve()

    set_enabled(False, None, owner=paths.root)  # never another install's entry
    print("Start at login: removed")
    desktop.remove_launchers(paths)
    print("Shortcuts: removed")
    app = desktop.app_location(paths)
    if IS_MAC and app.exists():
        shutil.rmtree(app, ignore_errors=True)
        print(f"Removed {app}")

    if args.purge:
        if not args.yes:
            answer = input("Delete this computer's Signal keys, settings, history and models? Type 'delete': ")
            if answer.strip() != "delete":
                print("Kept your data. Uninstall finished without --purge.")
                return 0
        for name in GENERATED:
            target = paths.root / name if name in ("runtime", ".venv") else paths.home / name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
        print("Deleted Signal Scribe's data. You can now delete this folder.")
    else:
        print(f"Your Signal link, settings and history are still in {paths.home}.")
        print("Run again with --purge to delete them.")
    print('Also remove "Signal Scribe" on your phone: Signal > Settings > Linked devices.')
    return 0


if __name__ == "__main__":
    sys.exit(main())

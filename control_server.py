"""Private JSON-lines API for the desktop app. See scribe/control/PROTOCOL.md."""
import json
import sys

from scribe.control.server import handle_line
from scribe.control.service import ControlService
from scribe.logs import setup
from scribe.paths import resolve


def main():
    # stdout carries the protocol, so nothing else may print to it.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    paths = resolve().ensure()
    setup(paths.logs, "control")
    service = ControlService(paths)
    for raw in sys.stdin:
        print(json.dumps(handle_line(service, raw), separators=(",", ":"), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

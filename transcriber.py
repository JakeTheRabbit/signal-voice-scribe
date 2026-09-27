"""Signal Scribe engine. The desktop app starts this; see scribe/engine.py."""
import sys

from scribe.engine import main

if __name__ == "__main__":
    sys.exit(main())

"""Link this computer to Signal. The desktop app starts this; see scribe/linking.py."""
import sys

from scribe.linking import main

if __name__ == "__main__":
    sys.exit(main())

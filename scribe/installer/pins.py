"""Pinned third-party downloads. Update versions and checksums together.

signal-cli holds your Signal keys, so its archive is pinned to an exact
SHA-256 (from the GitHub release's published asset digest). Java comes from
Eclipse Temurin via the Adoptium API, which publishes a SHA-256 per build.
"""

SIGNAL_CLI_VERSION = "0.14.8"
SIGNAL_CLI_URL = (f"https://github.com/AsamK/signal-cli/releases/download/v{SIGNAL_CLI_VERSION}/"
                  f"signal-cli-{SIGNAL_CLI_VERSION}.tar.gz")
SIGNAL_CLI_SHA256 = "ccd408e831eff7e41ebaaf309704840bb00d78a7869f35ad700dbae5b5a5bb65"

JAVA_MAJOR = 25
ADOPTIUM_API = ("https://api.adoptium.net/v3/assets/latest/{major}/hotspot"
                "?architecture={arch}&image_type=jre&os={os}&vendor=eclipse")

REPOSITORY = "JakeTheRabbit/signal-voice-scribe"
RELEASES = f"https://github.com/{REPOSITORY}/releases"

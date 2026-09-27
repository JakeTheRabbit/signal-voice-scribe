#!/usr/bin/env bash
# Install (or update) Signal Scribe for the current macOS or Linux user. No sudo needed.
#
# Sets up everything inside this folder: Python and its packages (via uv), Java,
# signal-cli, the Whisper speech model and the desktop app. Run it again at any
# time to update or repair; your settings, Signal link and history are kept.
#
#   ./install.sh                 # desktop app (window + tray icon)
#   ./install.sh --headless      # servers: no window, runs in the background
#   ./install.sh --help          # all options
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$ROOT/runtime"
UV_VERSION="0.12.19"

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

  --headless          no desktop app; run the engine in the background at login (servers)
  --gpu auto|yes|no   NVIDIA GPU acceleration on Linux (default: auto)
  --model NAME        Whisper model to download now: auto (default), tiny, base, small,
                      medium, large-v3-turbo, ... or none to download on first use
  --desktop WHAT      download (default), build (from source; needs Rust + pnpm), skip,
                      or a path to a local build
  --no-autostart      don't start at login
  --no-shortcuts      don't add an app-menu entry
  --no-launch         don't open the app when finished
EOF
}

GPU="auto"
PASS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --gpu) GPU="${2:-}"; shift 2 ;;
        --gpu=*) GPU="${1#*=}"; shift ;;
        --model|--desktop) PASS+=("$1" "${2:-}"); shift 2 ;;
        --model=*|--desktop=*|--headless|--no-autostart|--no-shortcuts|--no-launch) PASS+=("$1"); shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
case "$GPU" in auto|yes|no) ;; *) echo "--gpu must be auto, yes or no" >&2; exit 2 ;; esac

echo "Signal Scribe installer"
[ -f "$ROOT/pyproject.toml" ] || { echo "Run install.sh from the Signal Scribe folder." >&2; exit 1; }

# Stop this install's own processes (not the installer itself).
if command -v pkill >/dev/null 2>&1; then
    ROOT_RE="$(printf '%s' "$ROOT" | sed 's/[][\.*^$(){}?+|]/\\&/g')"
    pkill -f "$ROOT_RE/(transcriber|control_server|link)\.py" 2>/dev/null || true
    pkill -f "$ROOT_RE/runtime/(jre|desktop)/" 2>/dev/null || true
fi

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

fetch() {
    if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 3 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then wget -q -O "$2" "$1"
    else echo "Install curl or wget first." >&2; exit 1; fi
}

# 1. uv: a single-file Python installer and package manager (https://docs.astral.sh/uv/).
# The pinned copy is used even if you have uv, so it always matches the lockfile.
UV="$RUNTIME/uv/uv"
if [ ! -x "$UV" ] || [ "$("$UV" --version 2>/dev/null | cut -d' ' -f2)" != "$UV_VERSION" ]; then
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64)   TARGET="aarch64-apple-darwin";      HASH="a9a8df1eedeb192f2e47e40e2faabfb387db4b850209118786d42f89dde3e0ba" ;;
        Darwin-x86_64)  TARGET="x86_64-apple-darwin";       HASH="cb5fa57bafe68fc0fb94b17f06bee0b0b9a7feb94ccbd110445afa0696e39273" ;;
        Linux-x86_64)   TARGET="x86_64-unknown-linux-gnu";  HASH="23bf5552d220e0842b65c862097b2ebaeba0064b74eda5e565e77fd25969d8c8" ;;
        Linux-aarch64|Linux-arm64)
                        TARGET="aarch64-unknown-linux-gnu"; HASH="0804e9b164c64b6914182d5920c08551958a095986f10a3731056df701126436" ;;
        *) echo "Unsupported system: $(uname -s) $(uname -m)" >&2; exit 1 ;;
    esac
    echo "Downloading uv $UV_VERSION..."
    mkdir -p "$RUNTIME/uv"
    ARCHIVE="$RUNTIME/uv/uv.tar.gz"
    fetch "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$TARGET.tar.gz" "$ARCHIVE"
    if [ "$(sha256_of "$ARCHIVE")" != "$HASH" ]; then
        rm -f "$ARCHIVE"
        echo "The uv download failed its checksum and was deleted. Try again." >&2
        exit 1
    fi
    tar -xzf "$ARCHIVE" -C "$RUNTIME/uv" --strip-components=1
    rm -f "$ARCHIVE"
fi

# 2. Python 3.12 and packages, kept inside this folder.
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
export UV_PYTHON_PREFERENCE="only-managed"
export UV_PROJECT_ENVIRONMENT="$ROOT/.venv"
SYNC=(sync --frozen --no-dev --python 3.12 --directory "$ROOT")
if [ "$(uname -s)" = "Linux" ] && { [ "$GPU" = "yes" ] || { [ "$GPU" = "auto" ] && command -v nvidia-smi >/dev/null 2>&1; }; }; then
    echo "NVIDIA GPU found: including GPU acceleration (about 1 GB extra)."
    SYNC+=(--extra cuda)
fi
echo "Installing Python and packages..."
"$UV" "${SYNC[@]}"

if [ "$(uname -s)" = "Linux" ] && [ -n "${XDG_CURRENT_DESKTOP:-}" ] && [[ " ${PASS[*]-} " != *" --headless "* ]]; then
    case "${XDG_CURRENT_DESKTOP}" in
        *GNOME*) echo "Note: GNOME shows tray icons only with the AppIndicator extension (e.g. package gnome-shell-extension-appindicator)." ;;
    esac
fi

# 3. Everything else is shared with Windows.
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m scribe.installer "${PASS[@]+"${PASS[@]}"}"

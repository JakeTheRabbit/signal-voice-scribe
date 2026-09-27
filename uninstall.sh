#!/usr/bin/env bash
# Remove Signal Scribe's start-at-login entry, app-menu entry and desktop app (macOS/Linux).
# Your Signal link, settings and history are kept unless you pass --purge.
# Also remove "Signal Scribe" from your phone: Signal > Settings > Linked devices.
#
#   ./uninstall.sh            keep data
#   ./uninstall.sh --purge    also delete data, models and the runtime
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v pkill >/dev/null 2>&1; then
    ROOT_RE="$(printf '%s' "$ROOT" | sed 's/[][\.*^$(){}?+|]/\\&/g')"
    pkill -f "$ROOT_RE/(transcriber|control_server|link)\.py" 2>/dev/null || true
    pkill -f "$ROOT_RE/runtime/(jre|desktop)/" 2>/dev/null || true
    sleep 2
fi

if [ -x "$ROOT/.venv/bin/python" ]; then
    cd "$ROOT" && exec "$ROOT/.venv/bin/python" -m scribe.installer.uninstall "$@"
fi

# The Python environment is gone: remove what we can directly.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now signal-scribe.service >/dev/null 2>&1 || true
fi
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/signal-scribe.service" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/signal-scribe.desktop" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/applications/signal-scribe.desktop" \
      "$HOME/Library/LaunchAgents/io.github.jaketherabbit.signalscribe.plist"
echo "Start at login and launchers removed. Delete this folder to remove everything else."

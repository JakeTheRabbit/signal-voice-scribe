# Running headless (server, NAS, Docker)

Signal Scribe doesn't need a screen. On a machine that's always on (a home server, NAS or spare PC)
you can run just the engine and manage it from the command line. Transcripts still arrive in Signal
exactly the same way.

These options work on x86-64 Linux, and the command line also works on Windows and macOS.

## Docker Compose

```bash
git clone https://github.com/JakeTheRabbit/signal-voice-scribe.git
cd signal-voice-scribe
# optional: set your time zone in compose.yaml (TZ)
docker compose build
docker compose run --rm signal-scribe link     # scan the QR code with your phone
docker compose up -d                           # run in the background
docker compose logs -f                         # watch it work
```

Everything the engine keeps (Signal keys, settings, history, the speech model) is in
`./signal-scribe-data`. Back that folder up, and keep it private: it contains this device's Signal keys.

Useful commands:

```bash
docker compose run --rm signal-scribe status
docker compose run --rm signal-scribe doctor
docker compose run --rm signal-scribe config delivery.mode chat
docker compose restart                         # apply changed settings
```

The image runs as an unprivileged user (uid 1000) and uses the CPU. To choose a smaller or larger
model: `docker compose run --rm signal-scribe config transcription.model base`.

## Without Docker (systemd)

```bash
./install.sh --headless
./signal-scribe link
```

On Linux with systemd, `--headless` installs a user service (`signal-scribe.service`) that starts
at login and restarts after a failure. To keep it running when you're not logged in:

```bash
loginctl enable-linger "$USER"
systemctl --user status signal-scribe
journalctl --user -u signal-scribe      # or read logs/engine.log
```

On macOS `--headless` uses a LaunchAgent, and on Windows a start-at-login entry.

## The command line

`signal-scribe` (Windows: `signal-scribe.cmd`) in the install folder:

| Command | What it does |
|---|---|
| `link` | Link to your Signal account; shows a QR code in the terminal. |
| `run` | Run the engine in this terminal (Ctrl+C stops it cleanly). |
| `status` | Link status, engine state, model, and today's counts. |
| `doctor` | Checks Java, signal-cli, settings and the model. Exits non-zero on problems. |
| `transcribe FILE` | Transcribe an audio file locally, to test your setup. Nothing is sent. |
| `download-model [NAME]` | Download a Whisper model now instead of on first use. |
| `config [KEY [VALUE]]` | Show or change settings, e.g. `config transcription.language de`. |
| `unlink` | Delete this computer's Signal keys (after removing it on your phone). |

Settings are in `config.json` (see [how-it-works.md](how-it-works.md#settings)). Restart the
engine after changing them.

## Where the data lives

By default everything is inside the install folder. Set `SIGNAL_SCRIBE_HOME=/some/path` to keep
`config.json`, `data/`, `logs/` and `models/` somewhere else (the Docker image uses `/data`).

## Exit codes

`signal-scribe run` exits with `0` when stopped, `2` when it needs you (not linked, removed from
your phone's Linked devices, or signal-cli/Java missing), `3` if another copy is already running
for the same data folder, and `1` on an unexpected error. Service managers should not restart it
on `2` or `3`.

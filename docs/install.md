# Installing Signal Scribe

The short version is in the [README](../README.md#install). This page covers the details.

## What the installer does

`install.ps1` (Windows) and `install.sh` (macOS, Linux) do the same thing:

1. **uv.** If you don't already have [uv](https://docs.astral.sh/uv/), a pinned version is downloaded
   into `runtime/uv/` and checked against its SHA-256.
2. **Python 3.12 and packages.** uv downloads its own Python into `runtime/python/` and installs the
   exact package versions in `uv.lock` into `.venv/`. Your system Python is not used or changed.
3. **Java 25.** If there's no Java 25 or newer on the computer, the Eclipse Temurin runtime for your
   system is downloaded into `runtime/jre/` and checked against the checksum Adoptium publishes.
4. **signal-cli.** The pinned release (see `scribe/installer/pins.py`) is downloaded into
   `runtime/signal-cli/` and checked against its SHA-256.
5. **Settings.** A `config.json` with the defaults is created (only if you don't have one).
6. **Speech model.** The Whisper model that suits your computer is downloaded into `models/`.
7. **Desktop app.** The build for your system is downloaded from this project's GitHub release for
   the same version and checked against the release's `SHA256SUMS.txt`. Shortcuts and start-at-login
   are added.

Everything lives in the install folder, so nothing else on your system changes (apart from the
shortcuts, the start-at-login entry, and on macOS the app in `~/Applications`).

Re-running the installer is safe: it updates what changed and keeps your settings, Signal link and
history.

## Options

| `install.ps1` | `install.sh` | What it does |
|---|---|---|
| `-Headless` | `--headless` | No desktop app; the engine runs in the background at login. For servers. |
| `-Gpu auto\|yes\|no` | `--gpu auto\|yes\|no` | NVIDIA GPU acceleration (about 1 GB extra). `auto` checks for an NVIDIA driver. Linux and Windows only. |
| `-Model NAME` | `--model NAME` | Download and use this Whisper model, or `none` to download on first use. |
| `-Desktop build` | `--desktop build` | Build the desktop app from source instead of downloading it (needs Rust and pnpm). |
| `-Desktop skip` | `--desktop skip` | Same as headless. |
| `-NoAutostart` | `--no-autostart` | Don't start at login. |
| `-NoShortcuts` | `--no-shortcuts` | No Start menu / app menu entries. |
| `-NoDesktopIcon` | | No shortcut on the Windows desktop. |
| `-NoLaunch` | `--no-launch` | Don't open the app at the end. |

## Choosing a model

| Model | Download | Good for |
|---|---|---|
| `tiny`, `base` | 75–145 MB | Old or slow computers. Less accurate. |
| `small` | ~480 MB | **Default without an NVIDIA GPU.** Good accuracy, about 3 s for an 8 s note on a recent CPU. |
| `medium` | ~1.5 GB | More accurate, slower on CPU. |
| `large-v3-turbo` | ~1.6 GB | **Default with an NVIDIA GPU.** Very accurate; well under a second per note on a GPU. |
| `large-v3` | ~3 GB | Most accurate, slowest. |
| `*.en` variants | same | English-only versions; slightly better for English. |

Change it any time on the **Transcription** page (or `signal-scribe config transcription.model small`).
A new model downloads the first time it's used.

## NVIDIA GPUs

With `-Gpu auto` (the default) the installer adds the CUDA libraries when it finds an NVIDIA
driver (`nvidia-smi`). You need a reasonably recent driver; no CUDA toolkit install is required.
If the GPU can't be used for any reason, Signal Scribe falls back to the CPU and says so on the
Overview page.

Apple silicon Macs run Whisper on the CPU, which is fast enough for voice notes.

## Updating

Download or `git pull` the new version into the same folder, then run the installer again.

## Moving the install folder

Move the folder, then run the installer again from the new location so the shortcuts and
start-at-login entry point to it.

## Uninstalling

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1          # Windows, keeps your data
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge   # also deletes it
```

```bash
./uninstall.sh            # macOS/Linux, keeps your data
./uninstall.sh --purge    # also deletes it
```

Then delete the folder, and remove **Signal Scribe** from **Linked devices** on your phone.

## ARM Linux

signal-cli ships its Signal protocol library (libsignal) for x86-64 Linux, Windows and macOS only.
On ARM Linux (Raspberry Pi, ARM servers) the installer still works, but you need to provide
libsignal yourself as described in the signal-cli wiki:
[Provide native lib for libsignal](https://github.com/AsamK/signal-cli/wiki/Provide-native-lib-for-libsignal).

## Behind a proxy or offline

The installer uses standard HTTPS downloads from github.com, api.adoptium.net, astral.sh-hosted
GitHub releases, pypi.org/files.pythonhosted.org and huggingface.co. After installation, Signal
Scribe only needs Signal's own servers (through signal-cli).

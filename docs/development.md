# Development

## Layout

| Path | What |
|---|---|
| `scribe/` | Python package: engine, signal-cli client, job queue, transcription, history, installer, CLI |
| `scribe/control/` | The private API the desktop app uses ([PROTOCOL.md](../scribe/control/PROTOCOL.md)) |
| `transcriber.py`, `control_server.py`, `link.py` | Entry points the desktop app starts |
| `desktop/src/` | React + TypeScript UI |
| `desktop/src-tauri/` | Rust shell: window, tray, process supervision |
| `tests/` | Python tests (pytest) |
| `install.ps1`, `install.sh` | Bootstrap uv and Python, then run `python -m scribe.installer` |

## Python

```bash
uv sync                      # creates .venv with the locked versions, plus pytest
uv run pytest -q
uv run signal-scribe doctor
```

The tests never touch the network or Signal: signal-cli is replaced by small fake scripts and
Whisper by a stub. To also run a real transcription test, point `SIGNAL_SCRIBE_MODELS` at a folder
containing the `tiny.en` model (`uv run signal-scribe --home /tmp/x download-model tiny.en`).

To run the engine against your own account for development, use a separate folder via
`SIGNAL_SCRIBE_HOME` and link it as its own device.

## Desktop app

Needs Node 24, pnpm (the version in `desktop/package.json`), the Rust toolchain in
`desktop/rust-toolchain.toml`, and [Tauri's prerequisites](https://v2.tauri.app/start/prerequisites/)
for your system.

```bash
cd desktop
pnpm install --frozen-lockfile
pnpm test                    # vitest
pnpm build                   # typecheck + production UI build
cargo test --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings
pnpm tauri dev -- -- --root "$(cd .. && pwd)"    # run it against this checkout
pnpm tauri build --no-bundle                      # release binary in src-tauri/target/release
```

Install a local build into your checkout with
`uv run python -m scribe.installer --desktop desktop/src-tauri/target/release/signal-scribe`
(`signal-scribe.exe` on Windows).

### Demo mode and screenshots

`pnpm dev` serves the UI at <http://127.0.0.1:1420/?demo=1> with fictional data and no backend.
Extra parameters: `page=History`, `theme=light|dark`, `state=unlinked`, `dialog=link`.

`pnpm screenshots` (with `pnpm dev` running) regenerates every image in `docs/images/` using
headless Chrome or Edge.

## Releasing

1. Update the version in `pyproject.toml`, `scribe/__init__.py`, `desktop/package.json`,
   `desktop/src-tauri/Cargo.toml` and `desktop/src-tauri/tauri.conf.json`, and add a section to
   `CHANGELOG.md`.
2. Commit, then tag: `git tag v1.2.3 && git push origin v1.2.3`.
3. The Release workflow builds the desktop app for Windows, macOS and Linux and publishes it with
   `SHA256SUMS.txt`. The installers download the build that matches their own version.

## Updating signal-cli

Change `SIGNAL_CLI_VERSION` and `SIGNAL_CLI_SHA256` in `scribe/installer/pins.py` and the matching
`ARG`s in the `Dockerfile`. The checksum is on the release's asset list (`digest`), or:
`gh api repos/AsamK/signal-cli/releases/tags/v0.14.8 --jq '.assets[] | "\(.name) \(.digest)"'`.
Read its changelog for changes to the Java version or JSON-RPC output.

## Principles

- Audio and transcripts stay on the computer. Anything that would change that doesn't belong here.
- Never lose a voice note; never send a transcript twice.
- Logs record events, never content.
- No personal data in the repository: tests use the reserved `+1 555-555-01xx` numbers and fictional
  names, and `tests/test_repository_safety.py` checks for common leaks.

# Signal Scribe desktop app

The window and tray icon, built with [Tauri 2](https://tauri.app): React + TypeScript for the UI
(`src/`) and a small Rust shell (`src-tauri/`). Setup, tests and builds are described in
[docs/development.md](../docs/development.md).

## How the shell is organised

| File | Responsibility |
|---|---|
| `src-tauri/src/lib.rs` | Window, tray menu, and the complete list of commands the UI may call |
| `src-tauri/src/runtime.rs` | Finding the install folder: `--root`, `SIGNAL_SCRIBE_ROOT`, a nearby install, or the per-user pointer the installer writes |
| `src-tauri/src/engine.rs` | Starting, watching and stopping the engine with back-off; no restart when the engine says it needs the user (exit code 2) or another engine owns the folder (3) |
| `src-tauri/src/process.rs` | Child processes as a tree (Job Objects on Windows, process groups elsewhere); graceful stop by closing stdin |
| `src-tauri/src/control.rs` | The JSON-lines client for `control_server.py`: one request at a time, timeouts, and mutations are never retried |
| `src-tauri/src/state.rs` | Linking, the start-on-launch decision and shutdown |

The UI talks to the shell only through the commands in `lib.rs`. It gets no file-system or shell
access, and error messages are fixed strings chosen by the shell, not text from Python.

## Command-line flags

- `--root <folder>` use a specific install folder.
- `--hidden` start in the tray without opening the window (used when starting at login).

## Demo

`pnpm dev`, then open <http://127.0.0.1:1420/?demo=1>: the whole UI with fictional data and no
backend. See [docs/development.md](../docs/development.md#demo-mode-and-screenshots).

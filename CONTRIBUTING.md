# Contributing

Thanks for helping. Signal Scribe has a narrow purpose (read voice notes privately) and a few
firm rules:

1. **Audio and transcripts stay on the user's computer.** No cloud services, analytics or telemetry.
2. **Never lose a voice note, never send a transcript twice.** Changes to the engine need tests
   that show both.
3. **No personal data** in code, tests, screenshots, issues or logs: use the reserved
   `+1 555-555-01xx` numbers and fictional names.

## Getting started

See [docs/development.md](docs/development.md) for setting up, running the tests and building the
desktop app. Before opening a pull request:

```bash
uv run pytest -q
cd desktop && pnpm format:check && pnpm test && pnpm build
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path src-tauri/Cargo.toml
```

Keep changes focused, explain the "why" in the pull request, and update the docs and
`CHANGELOG.md` when behaviour changes.

## Reporting bugs

Use the issue form. Include **Diagnostics → Copy results** and the relevant part of
`logs/engine.log`. Security problems: see [SECURITY.md](SECURITY.md).

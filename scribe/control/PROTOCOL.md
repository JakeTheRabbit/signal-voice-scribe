# Desktop control protocol

`control_server.py` reads one JSON request per line on stdin and writes one JSON response per line
on stdout. The desktop shell (`desktop/src-tauri/src/control.rs`) is the only client.

Request: `{"id": string|integer|null, "method": string, "params"?: object}` (at most 2 MiB).
Response: `{"id", "ok": true, "result"}` or `{"id", "ok": false, "error": {"code", "message"}}`.

Unknown methods, missing or extra parameters and non-finite numbers are rejected. Error codes are
stable; messages are for people and never contain message text, paths or secrets.

| Method | Params | Result |
|---|---|---|
| `state.get` | — | `{linked, unlinked, account, schema_version, engine: heartbeat \| null}` |
| `config.get` | — | the settings with defaults filled in |
| `config.save` | `{config}` (a partial update) | the saved settings; `invalid_config` names the bad setting |
| `history.list` | optional `query`, `direction` (`incoming`/`outgoing`), `kind` (`voice`), `conversation`, `limit` (1–1000) | `[{id, created_at, expires_at, conversation, sender, direction, kind, transcript, duration, language, media_available}]` |
| `history.conversations` | — | sorted chat names |
| `history.audio` | `{id}` | `{data_url}` (at most 16 MiB) |
| `history.delete` | `{ids}` (at most 1000) | `{deleted}` |
| `history.clear` | — | `{deleted}` |
| `diagnostics.get` | — | `{checks: [{name, status: ok\|warning\|error, detail}]}` |
| `link.status` | — | `{state: idle\|starting\|waiting\|linked\|failed, reason?, account?, qr?}`; `qr` is a PNG data URL, only while waiting |
| `autostart.get` | — | `{available, enabled}` |
| `autostart.set` | `{enabled}` | `{available, enabled}` |

The heartbeat (`data/engine-status.json`) is written by the engine every few seconds:
`{state, detail, problem, signal: {connected, since}, model: {model, device, compute_type, ready,
loading, fallback, error}, queue: {pending, today}, active, last, version, updated_at, stale}`.
`stale` is true when the engine hasn't updated it for 45 seconds.

Settings are merged section by section; unknown keys are kept. The one exception:
`history.conversation_retention_hours`, when present in an update, replaces the whole map.
Writes are atomic (temporary file, flush, rename).

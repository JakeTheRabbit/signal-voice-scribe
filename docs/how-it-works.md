# How Signal Scribe works

## The pieces

```text
Desktop app (Tauri: window + tray)                  Command line (signal-scribe)
   │ supervises                                          │
   ├── control_server.py   settings, history, link status (JSON lines over a private pipe)
   ├── link.py             linking: runs `signal-cli link`, writes a QR code image
   └── transcriber.py      the engine
          ├── signal-cli jsonRpc   ── Signal servers (as a linked device)
          ├── job queue (SQLite)   every voice note, before any work starts
          ├── Whisper (faster-whisper / CTranslate2)
          └── heartbeat file       what the app shows as status
```

- **signal-cli** is an unofficial Signal client. Linked with your phone, it receives the same
  messages Signal Desktop would. The engine keeps one `signal-cli jsonRpc` process running and
  reads events from it.
- **The engine** (`scribe/engine.py`) turns each voice note into a job, transcribes it with
  Whisper, and sends the text with signal-cli's `send`.
- **The desktop app** is a thin [Tauri](https://tauri.app) shell. It starts, watches and stops the
  engine, and talks to `control_server.py` for everything else. The web UI never gets file-system
  or shell access; every command it can call is listed in `desktop/src-tauri/src/lib.rs`.

## The life of a voice note

1. signal-cli receives a message with an attachment marked as a voice note, downloads it into
   `data/attachments/`, and prints a `receive` event.
2. The engine writes a **job** to `data/jobs.sqlite3`. The job id is a hash of the account, sender,
   message timestamp and attachment id, so a repeated event can't create a second job. Any other
   attachments in the message (photos, videos, files) are deleted right away.
3. The worker transcribes the oldest due job. The transcript is saved on the job, so if sending
   fails it's retried without transcribing again.
4. If history is on, the transcript (and optionally the audio) is saved to `data/history.sqlite3`.
5. The text is sent: to Note to Self (with `notifySelf`, so your phone shows a notification), or as
   a reply quoting the voice note in the original chat.
6. The job is marked done and stripped of its content (only the id and outcome are kept, for 30
   days, to recognise repeats). The voice note file is deleted.

## Reliability decisions

| Situation | What happens |
|---|---|
| App closed, PC asleep or crashed mid-transcription | The job is still in the queue and finishes on the next start. |
| Same message delivered twice | Recognised by its job id; transcribed once. |
| Sending fails (offline, Signal rate limit) | Retried with back-off for up to 48 hours. |
| Signal isn't connected yet | Jobs wait and continue the moment it connects. |
| signal-cli exits | Restarted with back-off (2 s up to 5 min). |
| signal-cli stops responding | A ping every 5 minutes; two missed pings restart it. |
| The phone removes this computer | signal-cli marks the account unregistered; the engine stops and the app asks you to link again (exit code 2, no restart loop). |
| GPU unavailable or fails mid-run | Falls back to the CPU and shows a note. |
| Audio too long or unreadable | A short private notice instead of silence (can be turned off). |
| Transcription error | Retried 3 times, then a notice. |
| A setting in `config.json` is invalid | That one setting falls back to its default; the rest still apply. |
| Stopping | The app closes the engine's stdin; the engine finishes cleanly (a note in progress resumes next time) and closes signal-cli, before anything is killed. |
| Two copies for one data folder | A lock file (`data/.receiver.lock`) allows only one receiver. |

## Files

Everything is in the install folder unless `SIGNAL_SCRIBE_HOME` says otherwise:

| Path | What |
|---|---|
| `config.json` | Your settings. |
| `data/data/` | signal-cli's account: **this device's Signal keys.** |
| `data/attachments/` | Attachments while they're being processed (normally empty). |
| `data/jobs.sqlite3` | The work queue. |
| `data/history.sqlite3`, `data/history-media/` | Optional history. |
| `data/engine-status.json` | The engine's heartbeat. |
| `data/link/` | Linking progress; the QR image exists only while linking. |
| `logs/` | `engine.log`, `control.log`, `link.log`, `signal-cli.log`. |
| `models/` | Downloaded Whisper models. |
| `runtime/` | Java, signal-cli, the desktop app, uv and Python, as installed by the installer. |

## Settings

`config.json`, with the defaults:

```json
{
  "schema_version": 3,
  "transcription": {
    "model": "auto",            // or tiny, base, small, medium, large-v3-turbo, large-v3, *.en
    "device": "auto",           // or cpu, cuda
    "compute_type": "auto",     // or int8, int8_float16, float16, float32
    "language": null,           // null = detect; or a code such as "en", "de"
    "incoming": true,           // voice notes you receive
    "outgoing": true,           // voice notes you send
    "groups": true,             // include group chats
    "audio_files": false,       // also other audio attachments
    "max_minutes": 60           // longer notes get a notice instead
  },
  "delivery": {
    "mode": "note_to_self",     // or "chat": reply to the voice note in its chat
    "notify": true,             // show a notification for Note to Self transcripts
    "failure_notices": true     // tell you when a note can't be transcribed
  },
  "history": {
    "retention_hours": 0,       // 0 = off, -1 = until deleted
    "conversation_retention_hours": {},
    "keep_audio": true
  },
  "desktop": { "theme": "system", "start_engine_on_launch": true }
}
```

(The comments are for this page only; the real file is plain JSON.)

## Privacy model

- Audio is decoded and transcribed only on this computer.
- The Whisper model is downloaded once from Hugging Face (anonymously, telemetry disabled); after
  that it's loaded from disk without network access.
- Logs record events and timings, never message text, transcripts or names. `signal-cli.log`
  comes from signal-cli itself and can contain phone numbers in its warnings.
- The desktop app's web view has a strict content security policy: no remote content, and audio
  only from data the app itself provides.
- Anyone who can read `data/data/` can act as this linked device. Treat the folder like a signed-in
  Signal Desktop.

## Limitations

- Signal has no official API for this. signal-cli is maintained independently and updated
  regularly; Signal Scribe pins a tested version, and updates follow signal-cli releases.
- Signal allows a limited number of linked devices per account.
- The computer has to be on for transcripts to be created.

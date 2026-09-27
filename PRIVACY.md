# Privacy

Signal Scribe exists so you can read voice notes without playing them out loud, **without** sending
anyone's voice to a transcription company. This page describes exactly what it does with your data.

## What Signal Scribe can see

Signal Scribe is a linked device on your Signal account, like Signal Desktop. As a linked device,
signal-cli receives your incoming and sent messages (text, voice notes and other attachments) from
the time it was linked. Signal Scribe only acts on voice notes; everything else is ignored and any
downloaded files are deleted immediately.

## What leaves your computer

| Data | Goes to | When |
|---|---|---|
| Voice note audio | **Nowhere.** Transcribed locally. | Never |
| Transcripts | Your Note to Self, through Signal (end-to-end encrypted) | For every voice note |
| Transcripts | The original chat, through Signal | Only if you choose "In the same chat" |
| Failure notices ("couldn't transcribe…") | Your Note to Self | Only if a note can't be transcribed |
| A request for the speech model | Hugging Face (anonymous download) | Once per model |
| Installer downloads | GitHub, Adoptium, PyPI, Hugging Face | During installation |

Signal Scribe has no servers, no analytics and no telemetry. Hugging Face telemetry is disabled.

## What's stored on your computer

| Data | Where | How long |
|---|---|---|
| This device's Signal keys and account state | `data/data/` | Until you unlink/uninstall with `--purge` |
| Voice notes | `data/attachments/` | Until the transcript has been sent, normally seconds. If Signal can't be reached, sending is retried for up to 48 hours |
| Other attachments (photos, videos, files) | `data/attachments/` | Deleted as soon as the message is seen; a sweep removes leftovers |
| Work queue | `data/jobs.sqlite3` | While pending; afterwards only an id and outcome, for 30 days, to prevent duplicates |
| History (transcript, sender, chat name, optional audio) | `data/history.sqlite3`, `data/history-media/` | **Off by default.** When on: the period you choose, never longer than a disappearing message |
| Settings | `config.json` | Until you change them |
| Logs | `logs/` | Rotated at 1–2 MB, a few old copies each |

Signal Scribe's own logs record what happened (a voice note was queued, took 3 seconds, was sent)
and never message text or transcripts. `logs/signal-cli.log` is written by signal-cli and can
include phone numbers in its warnings.

Deleting history uses SQLite's secure delete and overwrites the audio file before removing it.
That makes casual recovery hard, but on SSDs, with backups or with file-system snapshots, no
software can guarantee data is gone.

## Disappearing messages

Signal Scribe's history never keeps a transcript longer than the original disappearing message.
A transcript sent to **Note to Self** follows Note to Self's own disappearing-messages setting, so
turn that on in Signal if you want transcripts to vanish too. Transcripts of disappearing notes are
marked "⏳ disappearing".

## Other people

Transcribing a voice note someone sent you is like reading it aloud to yourself: it stays on your
devices. If you choose to post transcripts into chats, everyone in that chat sees them. Respect the
people you talk to, and the laws where you live.

## Removing everything

Run the uninstaller with `--purge` / `-Purge` (or delete the install folder), and remove Signal
Scribe from **Linked devices** on your phone.

# Changelog

All notable changes to Signal Scribe. This project follows [semantic versioning](https://semver.org/).

## [1.0.0] - 2026-09-28

First public release.

### Added
- Transcribes Signal voice notes you receive and send, on your own computer with Whisper
  (faster-whisper). Nothing is uploaded to a transcription service.
- Transcripts arrive in your Note to Self (private, with a notification) or, if you prefer,
  as a reply to the voice note in the same chat.
- Desktop app for Windows, macOS and Linux with a tray icon, QR-code linking, status, searchable
  history with replay, and settings.
- Headless mode and a Docker image for home servers, with a `signal-scribe` command line.
- One-command installers that download everything they need (Python, Java, signal-cli and the
  speech model) into the install folder, with checksum verification.

### Reliability
- Voice notes are queued on disk before they're processed, so nothing is lost if the computer
  sleeps, crashes or restarts; repeats never produce duplicate transcripts.
- Automatic retries for sending, reconnection with back-off, a watchdog for an unresponsive
  signal-cli, and a clean shutdown that finishes or resumes work.
- Uses an NVIDIA GPU when available and falls back to the CPU if the GPU fails.
- Detects when the phone removes this computer from Linked devices and asks you to link again.

### Privacy
- Photos, videos and other attachments that signal-cli downloads are deleted as soon as they
  arrive; voice notes are deleted once transcribed.
- History is off by default; when on, it never outlives a disappearing message.
- Logs never contain message text or transcripts.

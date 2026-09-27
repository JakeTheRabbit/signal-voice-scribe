# Troubleshooting

Start with **Diagnostics** in the app (or `signal-scribe doctor`). It checks Java, signal-cli, the
settings, the speech model and whether the engine is running.

## A voice note didn't turn into text

1. Is the status at the top **Listening**? If it says **Paused**, click **Start**.
2. Look in **Note to Self** in Signal (or the original chat, if you chose that under Delivery).
3. The first note after installing can take a minute while the speech model loads or downloads.
4. Is it a voice note? Audio files sent as attachments are only transcribed if **Other audio files**
   is on (Transcription page).
5. Are group chats or your own notes turned off on the Transcription page?
6. Check `logs/engine.log` (Diagnostics → Open logs folder). Each voice note produces lines such as
   `queued an incoming voice note` and `sent a transcript`.

## "Signal removed this computer" / "Needs attention: unlinked"

The phone no longer lists Signal Scribe under Linked devices (it was removed, or the computer was
offline for about 30 days). Click **Link again** and scan the new code.

## The QR code expired or linking failed

Codes are valid for a few minutes. Click **Get a new code**. If it keeps failing:

- Check the computer's internet connection.
- Make sure you're scanning from **Settings → Linked devices → Link new device**, not the
  "add contact" QR scanner.
- Run the installer again to repair Java and signal-cli, then retry.

## The engine keeps restarting or says "Reconnecting"

signal-cli lost its connection to Signal. It retries automatically. If it persists, check
`logs/signal-cli.log` for the reason (and remove any phone numbers before sharing it).

## "Another copy of Signal Scribe is running"

Only one engine can use the same data folder. Close the other copy: the tray icon's **Quit**, or a
`signal-scribe run` in a terminal.

## Transcription is slow

- Choose a smaller model on the Transcription page (`small` or `base`).
- With an NVIDIA GPU, re-run the installer with `-Gpu yes` / `--gpu yes`.
- Signal Scribe uses half your CPU cores so the computer stays responsive.

## "GPU unavailable; using the CPU"

The NVIDIA libraries couldn't be loaded, or the GPU ran out of memory. Update your NVIDIA driver and
re-run the installer with `-Gpu yes` / `--gpu yes`. Everything keeps working on the CPU meanwhile.

## The wrong language comes out

Set the language explicitly on the Transcription page. Auto-detection can be fooled by very short
notes.

## Linux: no tray icon

GNOME needs the AppIndicator extension: install `gnome-shell-extension-appindicator` (or your
distribution's equivalent) and log out and in again. The window still works without it.

## macOS: "Signal Scribe can't be opened"

The installer downloads the app in a way that normally avoids this. If you downloaded the app
yourself from the Releases page, right-click it, choose **Open**, and confirm.

## Windows: "Windows protected your PC"

This appears for apps that aren't code-signed. It doesn't appear when the installer downloads the
app. If you see it, click **More info → Run anyway**, or re-run `install.ps1`.

## The installer failed

It stops with a message saying which step failed. Run it again: completed steps are kept. Behind
a proxy, see [install.md](install.md#behind-a-proxy-or-offline).

## Reporting a problem

Open an issue with the output of **Copy results** from Diagnostics and the relevant part of
`logs/engine.log`. Please don't include transcripts, phone numbers, names or QR codes.

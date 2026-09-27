# Security

## Reporting a vulnerability

Please report security problems privately through GitHub:
**[Report a vulnerability](https://github.com/JakeTheRabbit/signal-voice-scribe/security/advisories/new)**.
Don't open a public issue. You'll get a reply as soon as possible, and credit if you'd like it.

Security fixes are made on the latest release.

## What to protect

- **`data/`** holds this device's Signal keys. Anyone who can read it can act as this linked device
  and read new messages. Protect the computer with a login password and disk encryption, keep the
  data folder private, and remove the device from **Linked devices** on your phone if the computer
  is lost.
- **The desktop app** only allows its window to call a fixed list of commands (no file-system or
  shell access), refuses remote content, and never passes raw error text from the background
  service to the page.
- **Downloads** made by the installer are verified: uv and signal-cli against pinned SHA-256
  checksums, Java against Adoptium's published checksum, the desktop app against the release's
  `SHA256SUMS.txt`, and Python packages against the hashes in `uv.lock`.

## Known limits

- signal-cli is an unofficial client. Signal Scribe pins a specific, tested version.
- The desktop app builds are not code-signed. The installer verifies their checksums instead.
- Signal Scribe runs with your user account's permissions and needs no administrator rights.

"""Turning signal-cli events into voice-note jobs, and jobs into readable text."""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime

SAFE_ATTACHMENT_ID = re.compile(r"[A-Za-z0-9_\-][A-Za-z0-9_.\-]{0,199}\Z")
LATE_AFTER_SECONDS = 10 * 60


@dataclass(frozen=True)
class VoiceNote:
    """Everything needed to transcribe one voice note and deliver the text."""

    job_id: str
    account: str
    direction: str            # "incoming" or "outgoing"
    timestamp: int            # Signal message timestamp, milliseconds
    author: str               # ACI or number of whoever recorded it
    sender: str               # display name of whoever recorded it
    chat: str                 # contact or group name
    group_id: str | None
    recipient: str | None     # the other person in a one-to-one chat
    attachment_id: str
    content_type: str
    expires_in: int           # disappearing-message timer in seconds, 0 = off

    @property
    def target(self) -> dict:
        """signal-cli ``send`` parameters addressing the original chat."""
        return {"groupId": self.group_id} if self.group_id else {"recipient": [self.recipient]}

    def to_payload(self) -> dict:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict) -> "VoiceNote":
        return cls(**{field: payload.get(field) for field in cls.__dataclass_fields__})


def job_id(account: str, author: str, timestamp: int, attachment_id: str) -> str:
    raw = f"{account}\x1f{author}\x1f{timestamp}\x1f{attachment_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def is_voice(attachment: dict, include_audio_files: bool) -> bool:
    if attachment.get("isVoiceNote") is True or attachment.get("voiceNote") is True:
        return True
    return include_audio_files and str(attachment.get("contentType") or "").startswith("audio/")


def voice_notes(params: dict, settings: dict, names=None) -> tuple[list[VoiceNote], list[str]]:
    """Voice notes in one ``receive`` event, plus attachment ids to discard.

    ``settings`` is the ``transcription`` section. ``names`` optionally maps
    addresses and group ids to display names for outgoing messages.
    """
    envelope = params.get("envelope") if isinstance(params, dict) else None
    account = params.get("account") if isinstance(params, dict) else None
    if not isinstance(envelope, dict) or not isinstance(account, str) or not account:
        return [], []
    author = envelope.get("sourceUuid") or envelope.get("sourceNumber") or envelope.get("source") or ""
    if isinstance(envelope.get("dataMessage"), dict):
        message, direction = envelope["dataMessage"], "incoming"
        recipient = author
    elif isinstance((envelope.get("syncMessage") or {}).get("sentMessage"), dict):
        message, direction = envelope["syncMessage"]["sentMessage"], "outgoing"
        recipient = message.get("destinationUuid") or message.get("destinationNumber") or message.get("destination")
    else:
        return [], []
    attachments = [a for a in message.get("attachments") or [] if isinstance(a, dict)]
    discard = [a["id"] for a in attachments if isinstance(a.get("id"), str)]
    group = message.get("groupInfo") if isinstance(message.get("groupInfo"), dict) else None
    group_id = group.get("groupId") if group else None
    timestamp = message.get("timestamp") or envelope.get("timestamp")
    wanted = settings.get("outgoing" if direction == "outgoing" else "incoming", True)
    if (not wanted or (group_id and not settings.get("groups", True)) or type(timestamp) is not int
            or message.get("viewOnce") or message.get("remoteDelete") or message.get("reaction")
            or not (group_id or recipient) or not author):
        return [], discard

    lookup = names or {}
    if direction == "incoming":
        # Same source as outgoing notes when known, so a chat keeps one name in history.
        sender = lookup.get(author) or envelope.get("sourceName") or envelope.get("sourceNumber") or "Someone"
    else:
        sender = "You"
    if group_id:
        chat = (group or {}).get("groupName") or lookup.get(group_id) or "a group"
    elif direction == "incoming":
        chat = sender
    else:
        chat = lookup.get(recipient) or message.get("destinationNumber") or "a contact"
    expires = message.get("expiresInSeconds")
    notes = []
    for attachment in attachments:
        attachment_id = attachment.get("id")
        if not is_voice(attachment, settings.get("audio_files", False)) or not (
                isinstance(attachment_id, str) and SAFE_ATTACHMENT_ID.fullmatch(attachment_id)):
            continue
        notes.append(VoiceNote(
            job_id=job_id(account, author, timestamp, attachment_id), account=account,
            direction=direction, timestamp=timestamp, author=author, sender=str(sender)[:120],
            chat=str(chat)[:120], group_id=group_id, recipient=None if group_id else recipient,
            attachment_id=attachment_id, content_type=str(attachment.get("contentType") or ""),
            expires_in=int(expires) if isinstance(expires, int) and expires > 0 else 0))
    keep = {note.attachment_id for note in notes}
    return notes, [attachment for attachment in discard if attachment not in keep]


def duration_label(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def heading(note: VoiceNote, duration: float | None, now: float | None = None) -> str:
    """One line saying whose voice note this is, e.g. ``🎤 Sam · 0:42``."""
    if note.direction == "outgoing":
        who = f"You in {note.chat}" if note.group_id else f"You → {note.chat}"
    else:
        who = f"{note.sender} in {note.chat}" if note.group_id else note.sender
    parts = [f"🎤 {who}"]
    if duration:
        parts.append(duration_label(duration))
    now = time.time() if now is None else now
    sent = note.timestamp / 1000
    if now - sent > LATE_AFTER_SECONDS:
        when = datetime.fromtimestamp(sent)
        today = datetime.fromtimestamp(now).date() == when.date()
        parts.append("sent " + (when.strftime("%H:%M") if today else when.strftime("%d %b %H:%M")))
    if note.expires_in:
        parts.append("⏳ disappearing")
    return " · ".join(parts)


def transcript_message(note: VoiceNote, text: str, language: str | None, duration: float,
                       in_chat: bool, now: float | None = None) -> str:
    body = text.strip() or "(no speech detected)"
    if in_chat:
        # The message quotes the voice note, so the heading can stay short.
        label = f"🎤 Transcript · {duration_label(duration)}" if duration else "🎤 Transcript"
    else:
        label = heading(note, duration, now)
    if language and language != "en":
        label += f" · [{language}]"
    return f"{label}\n{body}"


def failure_message(note: VoiceNote, reason: str, now: float | None = None) -> str:
    return (f"{heading(note, None, now)}\n"
            f"⚠️ Couldn't transcribe this voice note ({reason}). Listen to it in Signal.")

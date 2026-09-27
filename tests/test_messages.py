from datetime import datetime

import pytest

from scribe import config
from scribe.messages import VoiceNote, failure_message, heading, job_id, transcript_message, voice_notes

from conftest import ACCOUNT, FRIEND

NOW_MS = 1_790_000_000_000
SETTINGS = config.defaults()["transcription"]


def voice(attachment_id="note1.m4a", **extra):
    return {"contentType": "audio/aac", "id": attachment_id, "size": 1000, "isVoiceNote": True, **extra}


def incoming(attachments, timestamp=NOW_MS, **message):
    return {"account": ACCOUNT, "envelope": {
        "sourceNumber": "+15555550111", "sourceUuid": FRIEND, "sourceName": "Sam", "timestamp": timestamp,
        "dataMessage": {"timestamp": timestamp, "attachments": attachments, "expiresInSeconds": 0, **message}}}


def outgoing(attachments, timestamp=NOW_MS, **message):
    return {"account": ACCOUNT, "envelope": {
        "sourceNumber": ACCOUNT, "sourceUuid": "aci-self", "timestamp": timestamp,
        "syncMessage": {"sentMessage": {"destinationNumber": "+15555550111", "destinationUuid": FRIEND,
                                        "timestamp": timestamp, "attachments": attachments, **message}}}}


def test_incoming_voice_note_becomes_a_job():
    notes, discard = voice_notes(incoming([voice()]), SETTINGS)
    assert discard == []
    [note] = notes
    assert (note.direction, note.sender, note.chat, note.author) == ("incoming", "Sam", "Sam", FRIEND)
    assert note.target == {"recipient": [FRIEND]}
    assert note.job_id == job_id(ACCOUNT, FRIEND, NOW_MS, "note1.m4a")


def test_outgoing_voice_note_uses_contact_name_and_destination():
    [note], _ = voice_notes(outgoing([voice()]), SETTINGS, {FRIEND: "Sam Rivers"})
    assert (note.direction, note.sender, note.chat) == ("outgoing", "You", "Sam Rivers")
    assert note.target == {"recipient": [FRIEND]}


def test_group_voice_note_targets_the_group():
    params = incoming([voice()], groupInfo={"groupId": "Z3JvdXAtaWQ=", "groupName": "Book club"})
    [note], _ = voice_notes(params, SETTINGS)
    assert note.target == {"groupId": "Z3JvdXAtaWQ="}
    assert heading(note, 42, now=NOW_MS / 1000) == "🎤 Sam in Book club · 0:42"


def test_other_attachments_are_marked_for_deletion():
    photo = {"contentType": "image/jpeg", "id": "photo.jpg"}
    notes, discard = voice_notes(incoming([photo, voice()]), SETTINGS)
    assert [n.attachment_id for n in notes] == ["note1.m4a"] and discard == ["photo.jpg"]


def test_plain_audio_files_only_when_enabled():
    song = {"contentType": "audio/mpeg", "id": "song.mp3", "isVoiceNote": False}
    assert voice_notes(incoming([song]), SETTINGS)[0] == []
    enabled = {**SETTINGS, "audio_files": True}
    assert len(voice_notes(incoming([song]), enabled)[0]) == 1


@pytest.mark.parametrize("settings, params", [
    ({**SETTINGS, "incoming": False}, incoming([voice()])),
    ({**SETTINGS, "outgoing": False}, outgoing([voice()])),
    ({**SETTINGS, "groups": False}, incoming([voice()], groupInfo={"groupId": "Z3JvdXA="})),
    (SETTINGS, incoming([voice()], viewOnce=True)),
    (SETTINGS, incoming([voice("../../escape")])),
    (SETTINGS, {"account": ACCOUNT, "envelope": {"receiptMessage": {}}}),
    (SETTINGS, {"envelope": {"dataMessage": {"attachments": [voice()]}}}),
])
def test_skipped_messages_produce_no_job(settings, params):
    assert voice_notes(params, settings)[0] == []


def test_payload_round_trip():
    [note], _ = voice_notes(incoming([voice()]), SETTINGS)
    assert VoiceNote.from_payload(note.to_payload()) == note


def test_note_to_self_text_says_who_and_how_long():
    [note], _ = voice_notes(incoming([voice()]), SETTINGS)
    text = transcript_message(note, " Running late. ", "en", 83, in_chat=False, now=NOW_MS / 1000)
    assert text == "🎤 Sam · 1:23\nRunning late."


def test_chat_text_is_short_and_tags_other_languages():
    [note], _ = voice_notes(incoming([voice()]), SETTINGS)
    assert transcript_message(note, "Hallo", "de", 5, in_chat=True) == "🎤 Transcript · 0:05 · [de]\nHallo"


def test_empty_speech_is_explicit():
    [note], _ = voice_notes(outgoing([voice()]), SETTINGS)
    assert transcript_message(note, "", None, 3, in_chat=False, now=NOW_MS / 1000).endswith("(no speech detected)")


def test_late_and_disappearing_notes_are_labelled():
    [note], _ = voice_notes(incoming([voice()], expiresInSeconds=3600), SETTINGS)
    later = NOW_MS / 1000 + 3 * 3600
    sent = datetime.fromtimestamp(NOW_MS / 1000).strftime("%H:%M")
    assert heading(note, 10, now=later) == f"🎤 Sam · 0:10 · sent {sent} · ⏳ disappearing"


def test_failure_message_tells_the_reader_what_to_do():
    [note], _ = voice_notes(incoming([voice()]), SETTINGS)
    text = failure_message(note, "the audio could not be read", now=NOW_MS / 1000)
    assert "Couldn't transcribe" in text and "Listen to it in Signal" in text

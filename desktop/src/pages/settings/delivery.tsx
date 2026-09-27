import {
  InfoNote,
  SettingsSection,
  ToggleField,
} from "../../components/settings";
import { useWorkspace } from "../../lib/workspace";
import { useConfirmation } from "./shared";

export function DeliveryPage() {
  const { config, update } = useWorkspace();
  const d = config.delivery;
  const confirmation = useConfirmation();
  const change = (patch: Partial<typeof d>) =>
    update({ delivery: { ...d, ...patch } });
  return (
    <div className="stack">
      <SettingsSection
        title="Where transcripts go"
        description="Transcripts are sent through Signal, so they show up on your phone and every linked device."
      >
        <div
          className="choice-list"
          role="radiogroup"
          aria-label="Where transcripts go"
        >
          <label
            className={`choice ${d.mode === "note_to_self" ? "selected" : ""}`}
          >
            <input
              type="radio"
              name="delivery"
              checked={d.mode === "note_to_self"}
              onChange={() => change({ mode: "note_to_self" })}
            />
            <span>
              <strong>Note to Self (recommended)</strong>
              <small>
                Private. Only you can read them. Each transcript says who sent
                the voice note and in which chat.
              </small>
            </span>
          </label>
          <label className={`choice ${d.mode === "chat" ? "selected" : ""}`}>
            <input
              type="radio"
              name="delivery"
              checked={d.mode === "chat"}
              onChange={() =>
                confirmation.request({
                  title: "Post transcripts in the chat?",
                  description:
                    "Each transcript is sent as a reply to its voice note, in the same chat, as you. Everyone in that chat, including groups, can read it.",
                  action: "Post in the chat",
                  onConfirm: () => change({ mode: "chat" }),
                })
              }
            />
            <span>
              <strong>In the same chat</strong>
              <small>
                A reply to the voice note, visible to everyone in the chat.
                Handy when the other person wants a text version too.
              </small>
            </span>
          </label>
        </div>
      </SettingsSection>
      <SettingsSection title="Notifications">
        <ToggleField
          label="Notify me on my phone"
          description="Note to Self messages normally arrive silently. This makes each transcript show a notification, which may display the text on your lock screen."
          checked={d.notify}
          disabled={d.mode === "chat"}
          onChange={(notify) => change({ notify })}
        />
        <ToggleField
          label="Tell me when a voice note can't be transcribed"
          description="Sends a short private notice (never into the chat) if a note is too long or unreadable."
          checked={d.failure_notices}
          onChange={(failure_notices) => change({ failure_notices })}
        />
      </SettingsSection>
      <InfoNote>
        Disappearing messages: if the voice note disappears, its Note to Self
        transcript doesn't, unless you turn on disappearing messages for Note to
        Self in Signal. Signal Scribe's own history never keeps a transcript
        longer than the original message.
      </InfoNote>
      {confirmation.dialog}
    </div>
  );
}

import {
  Field,
  InfoNote,
  SettingsSection,
  ToggleField,
} from "../../components/settings";
import { LANGUAGES, MODELS } from "../../lib/config";
import { useWorkspace } from "../../lib/workspace";
import { NumberField } from "./shared";

export function TranscriptionPage() {
  const { config, update } = useWorkspace();
  const t = config.transcription;
  const change = (patch: Partial<typeof t>) =>
    update({ transcription: { ...t, ...patch } });
  const knownLanguage = LANGUAGES.some(([code]) => code === (t.language || ""));
  return (
    <div className="stack">
      <SettingsSection
        title="Speech recognition"
        description="Whisper runs on this computer. The model downloads once, then works offline."
      >
        <Field
          label="Whisper model"
          description="Bigger models are more accurate but slower. Automatic picks Large v3 Turbo with an NVIDIA GPU, otherwise Small."
        >
          <select
            className="field-select"
            aria-label="Whisper model"
            value={t.model}
            onChange={(event) => change({ model: event.target.value })}
          >
            {MODELS.map(({ value, label, detail }) => (
              <option key={value} value={value}>
                {label} — {detail}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Language"
          description="Automatic detection works for most people. Choosing the language helps with short or noisy notes."
        >
          <select
            className="field-select"
            aria-label="Language"
            value={knownLanguage ? t.language || "" : "custom"}
            onChange={(event) =>
              change({
                language:
                  event.target.value === "custom"
                    ? t.language
                    : event.target.value || null,
              })
            }
          >
            {LANGUAGES.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
            {!knownLanguage && (
              <option value="custom">Other: {t.language}</option>
            )}
          </select>
        </Field>
        <Field
          label="Processor"
          description="Automatic uses an NVIDIA GPU when the GPU add-on is installed, and falls back to the CPU if the GPU fails."
        >
          <select
            className="field-select"
            aria-label="Processor"
            value={t.device}
            onChange={(event) => change({ device: event.target.value })}
          >
            <option value="auto">Automatic</option>
            <option value="cpu">CPU</option>
            <option value="cuda">NVIDIA GPU (CUDA)</option>
          </select>
        </Field>
      </SettingsSection>
      <SettingsSection title="Which voice notes">
        <ToggleField
          label="Voice notes I receive"
          description="Transcribe what other people send you."
          checked={t.incoming}
          onChange={(incoming) => change({ incoming })}
        />
        <ToggleField
          label="Voice notes I send"
          description="Also transcribe your own, so the conversation reads both ways."
          checked={t.outgoing}
          onChange={(outgoing) => change({ outgoing })}
        />
        <ToggleField
          label="Group chats"
          description="Include voice notes in groups, not only one-to-one chats."
          checked={t.groups}
          onChange={(groups) => change({ groups })}
        />
        <ToggleField
          label="Other audio files"
          description="Also transcribe audio attachments that weren't recorded as voice notes, such as forwarded recordings."
          checked={t.audio_files}
          onChange={(audio_files) => change({ audio_files })}
        />
        <NumberField
          label="Longest note to transcribe (minutes)"
          description="Longer recordings get a short notice instead, so a podcast can't tie up your computer."
          value={t.max_minutes}
          min={1}
          max={600}
          onChange={(max_minutes) => change({ max_minutes })}
        />
      </SettingsSection>
      {!t.incoming && !t.outgoing && (
        <InfoNote warning>
          Both directions are off, so nothing will be transcribed.
        </InfoNote>
      )}
    </div>
  );
}

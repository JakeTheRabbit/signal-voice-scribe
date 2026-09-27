import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "../../components/ui/button";
import { Dialog } from "../../components/ui/dialog";
import { Field, InfoNote } from "../../components/settings";
import { errorMessage } from "../../lib/tauri";
import { useWorkspace } from "../../lib/workspace";

export function useResourceError(error: unknown) {
  const { notice } = useWorkspace();
  const notify = useRef(notice);
  notify.current = notice;
  useEffect(() => {
    if (error) notify.current(errorMessage(error), true);
  }, [error]);
}

type Confirmation = {
  title: string;
  description: string;
  action: string;
  onConfirm: () => void | Promise<void>;
  destructive?: boolean;
};
export function useConfirmation() {
  const [pending, setPending] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const { notice, saving } = useWorkspace();
  async function confirm() {
    if (!pending || busy || saving) return;
    setBusy(true);
    try {
      await pending.onConfirm();
      setPending(null);
    } catch (error) {
      notice(errorMessage(error), true);
    } finally {
      setBusy(false);
    }
  }
  return {
    request: setPending,
    dialog: (
      <Dialog
        open={!!pending}
        onOpenChange={(open) => {
          if (!open && !busy) setPending(null);
        }}
        title={pending?.title || "Confirm change"}
        description={pending?.description}
      >
        <div className="inline-actions">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => setPending(null)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant={pending?.destructive ? "destructive" : "default"}
            disabled={busy || saving}
            onClick={() => void confirm()}
          >
            {busy ? "Working…" : pending?.action}
          </Button>
        </div>
      </Dialog>
    ),
  };
}

export function PageIntro({
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  // The shared shell owns the page heading and saved-state indicator.
  return <p className="subtle">{children}</p>;
}

export function NumberField({
  label,
  description,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string;
  description?: string;
  value: number;
  min: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const { notice } = useWorkspace();
  useEffect(() => setText(String(value)), [value]);
  const valid = (raw: string) =>
    raw.trim() !== "" &&
    Number.isFinite(Number(raw)) &&
    Number(raw) >= min &&
    (max === undefined || Number(raw) <= max) &&
    (step !== 1 || Number.isInteger(Number(raw)));
  return (
    <Field label={label} description={description}>
      <input
        className="field-input"
        type="number"
        aria-label={label}
        value={text}
        min={min}
        max={max}
        step={step}
        aria-invalid={!valid(text)}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          if (valid(next)) onChange(Number(next));
        }}
        onBlur={() => {
          if (!valid(text)) {
            setText(String(value));
            notice(
              `${label}: enter ${step === 1 ? "a whole number" : "a number"} from ${min}${max === undefined ? " or greater" : ` to ${max}`}. The previous value was kept.`,
              true,
            );
          }
        }}
      />
    </Field>
  );
}

export function ResourceStatus({
  loading,
  error,
  retry,
  subject,
}: {
  loading: boolean;
  error: unknown;
  retry: () => void;
  subject: string;
}) {
  if (loading)
    return (
      <p className="subtle" role="status">
        Loading {subject}…
      </p>
    );
  if (error)
    return (
      <InfoNote warning>
        <p>{errorMessage(error)}</p>
        <Button type="button" variant="outline" onClick={retry}>
          Reload {subject}
        </Button>
      </InfoNote>
    );
  return null;
}

import { useId, type ReactNode } from "react";
import { Info } from "lucide-react";
import { Switch } from "./ui/switch";

export function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="settings-section">
      <div className="section-heading">
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      <div className="settings-surface">{children}</div>
    </section>
  );
}
export function Field({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="field-row">
      <div className="field-copy">
        <div className="field-label">{label}</div>
        {description && <p>{description}</p>}
      </div>
      <div className="field-control">{children}</div>
    </div>
  );
}
export function ToggleField({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="field-row">
      <div className="field-copy">
        <label className="field-label" htmlFor={id}>
          {label}
        </label>
        {description && <p>{description}</p>}
      </div>
      <Switch
        id={id}
        label={label}
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
      />
    </div>
  );
}
export function InfoNote({
  children,
  warning = false,
}: {
  children: ReactNode;
  warning?: boolean;
}) {
  return (
    <div className={`info-note ${warning ? "warning" : ""}`}>
      <Info size={17} />
      <div>{children}</div>
    </div>
  );
}
export function EmptyState({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <p>{description}</p>
      {children}
    </div>
  );
}

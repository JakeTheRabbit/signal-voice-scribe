import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Field,
  InfoNote,
  SettingsSection,
  ToggleField,
} from "../../components/settings";
import { api, errorMessage, isDemo } from "../../lib/tauri";
import { useWorkspace } from "../../lib/workspace";
import type { Theme } from "../../lib/types";

export function AppPage() {
  const { config, update, notice } = useWorkspace();
  const queryClient = useQueryClient();
  const autostart = useQuery({
    queryKey: ["autostart"],
    queryFn: api.autostart,
    retry: false,
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.setAutostart(enabled),
    onSuccess: (value) => {
      queryClient.setQueryData(["autostart"], value);
      notice(
        value.enabled
          ? "Signal Scribe will start when you log in."
          : "Start at login is off.",
      );
    },
    onError: (error) => notice(errorMessage(error), true),
  });
  const state = useQuery({
    queryKey: ["state"],
    queryFn: api.state,
    retry: false,
  });
  return (
    <div className="stack">
      <SettingsSection
        title="Running in the background"
        description="Closing the window keeps Signal Scribe running in the tray (menu bar on macOS). Quit it from the tray icon."
      >
        <ToggleField
          label="Start at login"
          description="Open quietly in the tray when you log in, so voice notes are transcribed without you thinking about it."
          checked={!!autostart.data?.enabled}
          disabled={!autostart.data?.available || toggle.isPending}
          onChange={(enabled) => toggle.mutate(enabled)}
        />
        <ToggleField
          label="Start transcribing when the app opens"
          description="Resume automatically once Signal is linked. Turn off to start it yourself."
          checked={config.desktop.start_engine_on_launch}
          onChange={(start_engine_on_launch) =>
            update({ desktop: { ...config.desktop, start_engine_on_launch } })
          }
        />
      </SettingsSection>
      {autostart.isError && !isDemo && (
        <InfoNote warning>{errorMessage(autostart.error)}</InfoNote>
      )}
      <SettingsSection title="Appearance">
        <Field
          label="Theme"
          description="Follow your system, or pick light or dark."
        >
          <select
            className="field-select"
            aria-label="Theme"
            value={config.desktop.theme}
            onChange={(event) =>
              update({
                desktop: {
                  ...config.desktop,
                  theme: event.target.value as Theme,
                },
              })
            }
          >
            <option value="system">Same as system</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </Field>
      </SettingsSection>
      <SettingsSection title="About">
        <Field
          label="Version"
          description="Signal Scribe is free, open-source software (MIT licence)."
        >
          <span className="subtle">{state.data?.version || "—"}</span>
        </Field>
        <Field
          label="Source code"
          description="Report problems or read how it works."
        >
          <span className="subtle">
            github.com/JakeTheRabbit/signal-voice-scribe
          </span>
        </Field>
      </SettingsSection>
    </div>
  );
}

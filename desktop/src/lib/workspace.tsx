import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "./tauri";
import { configPatch, normalizeConfig } from "./config";
import type { AppConfig } from "./types";

interface WorkspaceValue {
  config: AppConfig;
  saved: AppConfig;
  dirty: boolean;
  saving: boolean;
  update: (patch: Partial<AppConfig>) => void;
  save: () => Promise<boolean>;
  discard: () => void;
  notice: (message: string, error?: boolean) => void;
  applyError?: string;
  clearApplyError?: () => void;
}
const Workspace = createContext<WorkspaceValue | null>(null);
export function useWorkspace() {
  const ctx = useContext(Workspace);
  if (!ctx) throw new Error("Workspace unavailable");
  return ctx;
}
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["config"],
    queryFn: async () => normalizeConfig(await api.config()),
    retry: false,
  });
  const [draft, setDraft] = useState<AppConfig>();
  const [saving, setSaving] = useState(false);
  const [applyError, setApplyError] = useState<string>();
  const [conflict, setConflict] = useState(false);
  const base = useRef<AppConfig | undefined>(undefined);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const [toast, setToast] = useState<{
    message: string;
    error: boolean;
  } | null>(null);
  useEffect(() => {
    if (!query.data) return;
    const edits =
      base.current && draftRef.current
        ? configPatch(base.current, draftRef.current)
        : {};
    const collisions = Object.keys(edits).some(
      (key) =>
        JSON.stringify(base.current?.[key]) !==
          JSON.stringify(query.data[key]) &&
        JSON.stringify(draftRef.current?.[key]) !==
          JSON.stringify(query.data[key]),
    );
    if (collisions) {
      setConflict(true);
      setToast({
        message:
          "Settings changed elsewhere. Your edits are preserved; discard and reapply them before saving.",
        error: true,
      });
    }
    setDraft({ ...structuredClone(query.data), ...edits });
    base.current = query.data;
  }, [query.data]);
  useEffect(() => {
    if (toast && !toast.error) {
      const timer = setTimeout(() => setToast(null), 6000);
      return () => clearTimeout(timer);
    }
  }, [toast]);
  const dirty = !!(
    draft &&
    query.data &&
    Object.keys(configPatch(query.data, draft)).length
  );
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  if (query.isError && !draft)
    return (
      <div className="connection-screen">
        <h1>Let’s reconnect.</h1>
        <p>{errorMessage(query.error)}</p>
        <button className="primary-action" onClick={() => query.refetch()}>
          Try connection again
        </button>
      </div>
    );
  if (!draft || !query.data)
    return (
      <div className="connection-screen" role="status">
        <span className="loading-dot" />
        <h1>Opening your workspace</h1>
        <p>Reading settings from this device…</p>
      </div>
    );
  function notice(message: string, error = false) {
    setToast({ message, error });
  }
  async function save() {
    if (!draft || !query.data || saving) return false;
    if (conflict) {
      notice(
        "Settings changed elsewhere. Discard and reapply your edits before saving.",
        true,
      );
      return false;
    }
    setSaving(true);
    try {
      const patch = configPatch(query.data, draft);
      const next = normalizeConfig(await api.saveConfig(patch));
      base.current = next;
      // Keep edits made while the save request was in flight.
      setDraft((current) => ({
        ...structuredClone(next),
        ...(current ? configPatch(draft!, current) : {}),
      }));
      queryClient.setQueryData(["config"], next);
      let message = "Changes saved.";
      if (Object.keys(patch).some((key) => key !== "desktop")) {
        try {
          const state = await api.state();
          if (state.engine.running) {
            await api.engine("restart");
            setApplyError(undefined);
            message = "Changes saved. Engine restarted.";
          }
        } catch (error) {
          setApplyError(
            "Settings were saved, but the engine could not reload them. It may still be using the previous settings. Pause and start it again before relying on these changes.",
          );
          notice(
            `Saved, but the engine could not restart: ${errorMessage(error)}`,
            true,
          );
          return true;
        }
      }
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      notice(message);
      return true;
    } catch (error) {
      notice(errorMessage(error), true);
      return false;
    } finally {
      setSaving(false);
    }
  }
  return (
    <Workspace.Provider
      value={{
        config: draft,
        saved: query.data,
        dirty,
        saving,
        update: (patch) => setDraft((current) => ({ ...current!, ...patch })),
        save,
        discard: () => {
          setDraft(structuredClone(query.data!));
          setConflict(false);
        },
        notice,
        applyError,
        clearApplyError: () => setApplyError(undefined),
      }}
    >
      {children}
      {toast && (
        <div
          role={toast.error ? "alert" : "status"}
          className={`toast ${toast.error ? "error" : ""}`}
        >
          <span>{toast.message}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast(null)}
          >
            ×
          </button>
        </div>
      )}
    </Workspace.Provider>
  );
}

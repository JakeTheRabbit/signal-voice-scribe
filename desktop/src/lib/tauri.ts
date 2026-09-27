import { invoke, isTauri } from "@tauri-apps/api/core";
import type {
  AppConfig,
  AppState,
  Autostart,
  Diagnostics,
  HistoryItem,
  LinkStatus,
} from "./types";

export const isDemo =
  !isTauri() && new URLSearchParams(location.search).get("demo") === "1";
async function native<T>(
  command: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  if (isDemo)
    return (await import("./demo")).demoInvoke(command, args) as Promise<T>;
  if (!isTauri())
    throw new Error("Open the Signal Scribe desktop app to use this page.");
  return invoke<T>(command, args);
}
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error)
    return String(error.message);
  return typeof error === "string"
    ? error
    : "Something went wrong. Try again or open Diagnostics.";
}
export const api = {
  state: () => native<AppState>("app_state"),
  config: () => native<AppConfig>("config_get"),
  saveConfig: (config: Partial<AppConfig>) =>
    native<AppConfig>("config_save", { config }),
  history: (filters: Record<string, unknown>) =>
    native<HistoryItem[]>("history_list", { filters }),
  conversations: () => native<string[]>("history_conversations"),
  audio: (id: string) => native<{ data_url: string }>("history_audio", { id }),
  deleteHistory: (ids: string[]) =>
    native<{ deleted: number }>("history_delete", { ids }),
  clearHistory: () => native<{ deleted: number }>("history_clear"),
  diagnostics: () => native<Diagnostics>("diagnostics_get"),
  autostart: () => native<Autostart>("autostart_get"),
  setAutostart: (enabled: boolean) =>
    native<Autostart>("autostart_set", { enabled }),
  link: () => native<void>("link_signal"),
  linkStatus: () => native<LinkStatus>("link_status"),
  cancelLink: () => native<void>("link_cancel"),
  openLogs: () => native<void>("open_logs"),
  engine: (action: "start" | "stop" | "restart") =>
    native<void>(`engine_${action}`),
};

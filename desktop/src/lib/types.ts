export type Theme = "system" | "light" | "dark";
export type Page =
  | "Overview"
  | "History"
  | "Transcription"
  | "Delivery"
  | "App"
  | "Diagnostics";

/** The engine process, as supervised by the desktop app. */
export interface EngineProcess {
  running: boolean;
  pid: number | null;
  status: string;
  exit_code?: number | null;
}

/** The engine's own heartbeat (scribe/engine.py). */
export interface Heartbeat {
  state:
    | "starting"
    | "running"
    | "reconnecting"
    | "stopping"
    | "stopped"
    | "needs_attention";
  detail?: string;
  problem?: string | null;
  signal?: { connected: boolean; since: number | null };
  model?: {
    model: string;
    device: string;
    compute_type: string;
    ready: boolean;
    loading: boolean;
    fallback?: string | null;
    error?: string | null;
  };
  queue?: { pending: number | null; today: Record<string, number> };
  active?: { direction: string; since: number } | null;
  last?: {
    at: number;
    direction: string;
    audio_seconds: number;
    seconds: number;
  } | null;
  version?: string;
  updated_at?: number;
  stale?: boolean;
}

export interface AppState {
  linked: boolean;
  unlinked: boolean;
  account: string;
  schema_version: number;
  engine: EngineProcess;
  heartbeat: Heartbeat | null;
  startup_error?: { code: string; message: string } | null;
  version?: string;
}

export interface HistoryItem {
  id: string;
  created_at: string;
  expires_at: string | null;
  conversation: string;
  sender: string;
  direction: "incoming" | "outgoing" | string;
  kind: string;
  transcript: string;
  duration: number | null;
  language: string | null;
  media_available: boolean;
}

export interface LinkStatus {
  state: "idle" | "starting" | "waiting" | "linked" | "failed";
  reason?: string;
  account?: string;
  qr?: string;
}

export interface Diagnostics {
  checks: {
    name: string;
    status: "ok" | "warning" | "error";
    detail: string;
  }[];
}

export interface Autostart {
  available: boolean;
  enabled: boolean;
}

export interface AppConfig {
  [key: string]: unknown;
  schema_version: number;
  transcription: {
    model: string;
    device: string;
    compute_type: string;
    language: string | null;
    incoming: boolean;
    outgoing: boolean;
    groups: boolean;
    audio_files: boolean;
    max_minutes: number;
    [key: string]: unknown;
  };
  delivery: {
    mode: "note_to_self" | "chat";
    notify: boolean;
    failure_notices: boolean;
    [key: string]: unknown;
  };
  history: {
    retention_hours: number;
    conversation_retention_hours: Record<string, number>;
    keep_audio: boolean;
    [key: string]: unknown;
  };
  desktop: {
    theme: Theme;
    start_engine_on_launch: boolean;
    [key: string]: unknown;
  };
}

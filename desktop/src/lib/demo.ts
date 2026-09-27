import type {
  AppConfig,
  AppState,
  Diagnostics,
  HistoryItem,
  LinkStatus,
} from "./types";

/*
 * An isolated, fictional workspace for trying the interface in a browser and for
 * the README screenshots: open http://127.0.0.1:1420/?demo=1. Nothing here talks to
 * Signal, reads files or runs the engine. Reloading resets it.
 *
 * Extra query parameters: page=History, theme=light|dark, state=unlinked,
 * dialog=link (open the linking dialog).
 */
const params = new URLSearchParams(
  typeof location === "undefined" ? "" : location.search,
);
const MINUTE = 60_000;
// Messages are placed before 17:40 today so screenshots look like a normal day.
const anchor = new Date();
anchor.setHours(17, 40, 0, 0);
const ANCHOR = anchor.getTime();

let config: AppConfig = {
  schema_version: 3,
  transcription: {
    model: "auto",
    device: "auto",
    compute_type: "auto",
    language: null,
    incoming: true,
    outgoing: true,
    groups: true,
    audio_files: false,
    max_minutes: 60,
  },
  delivery: { mode: "note_to_self", notify: true, failure_notices: true },
  history: {
    retention_hours: 168,
    conversation_retention_hours: { "Book club": 24 },
    keep_audio: true,
  },
  desktop: { theme: "system", start_engine_on_launch: true },
};
let linked = params.get("state") !== "unlinked";
let running = linked;
let autostart = true;
let linkStartedAt: number | null = null;

const examples: [string, string, string, number, string | null][] = [
  [
    "Alex",
    "Hey, just a heads-up: the table's booked for half seven. I'll wait outside if you're running late, no stress.",
    "incoming",
    24,
    null,
  ],
  [
    "Alex",
    "Perfect, I'll be there a few minutes early. Want me to grab the tickets on the way?",
    "outgoing",
    9,
    null,
  ],
  [
    "Book club",
    "So I finished it last night and I have thoughts. Mostly about the ending. Let's just say I did not see that coming.",
    "incoming",
    41,
    null,
  ],
  [
    "Priya",
    "Can you send me the address again? My phone deleted the message somehow. Also, is parking okay there?",
    "incoming",
    13,
    null,
  ],
  [
    "Jordan",
    "Hola, llego en diez minutos. Guárdame un sitio, por favor.",
    "incoming",
    6,
    "es",
  ],
  [
    "Priya",
    "It's the brick building next to the bakery. There's free parking round the back after six.",
    "outgoing",
    11,
    null,
  ],
];
let history: HistoryItem[] = examples.map(
  ([name, transcript, direction, seconds, language], i) => ({
    id: `${"d".repeat(31)}${i}`,
    conversation: name,
    sender:
      direction === "outgoing" ? "You" : name === "Book club" ? "Sam" : name,
    direction,
    kind: "voice",
    transcript,
    duration: seconds,
    language,
    media_available: true,
    created_at: new Date(ANCHOR - (i * 38 + 4) * MINUTE).toISOString(),
    expires_at: new Date(
      ANCHOR + (7 * 24 * 60 - (i * 38 + 4)) * MINUTE,
    ).toISOString(),
  }),
);

function state(): AppState {
  return {
    linked,
    unlinked: false,
    account: linked ? "+1 555-555-0100" : "",
    schema_version: 3,
    version: "1.0.0",
    engine: {
      running,
      pid: running ? 4242 : null,
      status: running ? "running" : "stopped",
      exit_code: null,
    },
    heartbeat: running
      ? {
          state: "running",
          detail: "Listening for voice notes",
          problem: null,
          signal: { connected: true, since: Date.now() / 1000 - 3 * 3600 },
          model: {
            model: "small",
            device: "cpu",
            compute_type: "int8",
            ready: true,
            loading: false,
            fallback: null,
          },
          queue: { pending: 0, today: { done: 12 } },
          active: null,
          last: {
            at: Date.now() / 1000 - 4 * 60,
            direction: "incoming",
            audio_seconds: 24,
            seconds: 3.1,
          },
          version: "1.0.0",
          updated_at: Date.now() / 1000,
          stale: false,
        }
      : null,
    startup_error: null,
  };
}

function link(): LinkStatus {
  if (linkStartedAt === null) return { state: "idle" };
  const elapsed = Date.now() - linkStartedAt;
  if (elapsed < 900) return { state: "starting" };
  if (elapsed < 45_000 || params.get("dialog") === "link")
    return { state: "waiting", qr: demoQr() };
  linked = true;
  linkStartedAt = null;
  return { state: "linked", account: "+1 555-555-0100" };
}

const diagnostics: Diagnostics = {
  checks: [
    {
      name: "Signal Scribe",
      status: "ok",
      detail: "Version 1.0.0, Python 3.12",
    },
    { name: "Settings", status: "ok", detail: "Valid" },
    { name: "Signal link", status: "ok", detail: "Linked to +1 555-555-0100" },
    { name: "Java", status: "ok", detail: "Java 25 found" },
    { name: "signal-cli", status: "ok", detail: "Version 0.14.8" },
    { name: "Whisper model", status: "ok", detail: "small on CPU (int8)" },
    { name: "Disk space", status: "ok", detail: "212.4 GB free" },
    { name: "Engine", status: "ok", detail: "Listening for voice notes" },
  ],
};

export async function demoInvoke(
  command: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  await new Promise((resolve) => setTimeout(resolve, 60));
  switch (command) {
    case "app_state":
      return state();
    case "config_get":
      return structuredClone(config);
    case "config_save":
      config = { ...config, ...(args.config as Partial<AppConfig>) };
      return structuredClone(config);
    case "history_list": {
      const filters = (args.filters || {}) as Record<string, string | number>;
      const query = String(filters.query || "").toLowerCase();
      return structuredClone(
        history
          .filter(
            (item) =>
              (!query ||
                `${item.transcript} ${item.conversation} ${item.sender}`
                  .toLowerCase()
                  .includes(query)) &&
              (!filters.direction || item.direction === filters.direction) &&
              (!filters.conversation ||
                item.conversation === filters.conversation),
          )
          .slice(0, Number(filters.limit) || 500),
      );
    }
    case "history_conversations":
      return [...new Set(history.map((item) => item.conversation))].sort();
    case "history_audio":
      return { data_url: demoAudio() };
    case "history_delete": {
      const ids = new Set(args.ids as string[]);
      const before = history.length;
      history = history.filter((item) => !ids.has(item.id));
      return { deleted: before - history.length };
    }
    case "history_clear": {
      const deleted = history.length;
      history = [];
      return { deleted };
    }
    case "diagnostics_get":
      return structuredClone(diagnostics);
    case "autostart_get":
      return { available: true, enabled: autostart };
    case "autostart_set":
      autostart = Boolean(args.enabled);
      return { available: true, enabled: autostart };
    case "link_signal":
      linkStartedAt = Date.now();
      return null;
    case "link_status":
      return link();
    case "link_cancel":
      linkStartedAt = null;
      return null;
    case "engine_start":
    case "engine_restart":
      running = linked;
      return state().engine;
    case "engine_stop":
      running = false;
      return state().engine;
    case "open_logs":
      return null;
    default:
      throw new Error(`The demo does not support ${command}.`);
  }
}

/** A QR-like picture for screenshots. It is not a valid code and links nothing. */
function demoQr() {
  const size = 29;
  let seed = 7;
  const random = () =>
    (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const finder = (x: number, y: number) =>
    x < 7 && y < 7
      ? x === 0 ||
        y === 0 ||
        x === 6 ||
        y === 6 ||
        (x > 1 && x < 5 && y > 1 && y < 5)
      : null;
  const cells: string[] = [];
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      const corner =
        finder(x, y) ?? finder(size - 1 - x, y) ?? finder(x, size - 1 - y);
      const on =
        corner === null
          ? (x < 8 && y < 8) ||
            (x > size - 9 && y < 8) ||
            (x < 8 && y > size - 9)
            ? false
            : random() > 0.52
          : corner;
      if (on)
        cells.push(`<rect x="${x + 4}" y="${y + 4}" width="1" height="1"/>`);
    }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size + 8} ${size + 8}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/><g fill="#111">${cells.join("")}</g></svg>`;
  return `data:image/svg+xml;base64,${btoa(svg)}`;
}

function demoAudio() {
  const sampleRate = 8000,
    samples = sampleRate,
    bytes = new Uint8Array(44 + samples * 2),
    view = new DataView(bytes.buffer);
  const text = (at: number, s: string) =>
    [...s].forEach((c, i) => (bytes[at + i] = c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, bytes.length - 8, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples * 2, true);
  for (let i = 0; i < samples; i++)
    view.setInt16(
      44 + i * 2,
      Math.sin((i * 2 * Math.PI * 440) / sampleRate) *
        2000 *
        Math.sin((Math.PI * i) / samples),
      true,
    );
  return (
    "data:audio/wav;base64," +
    btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(""))
  );
}

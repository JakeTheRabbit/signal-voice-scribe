import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App, { engineSummary } from "./App";
import { api } from "./lib/tauri";
import { normalizeConfig } from "./lib/config";
import type { AppConfig, AppState, Heartbeat } from "./lib/types";

let client: QueryClient;
let persisted: AppConfig;
let state: AppState;

const listening: Heartbeat = {
  state: "running",
  detail: "Listening for voice notes",
  signal: { connected: true, since: Date.now() / 1000 - 600 },
  model: {
    model: "small",
    device: "cpu",
    compute_type: "int8",
    ready: true,
    loading: false,
  },
  queue: { pending: 0, today: { done: 3 } },
  updated_at: Date.now() / 1000,
  stale: false,
};

beforeEach(() => {
  persisted = normalizeConfig({ schema_version: 3 });
  state = {
    linked: true,
    unlinked: false,
    account: "+1 555-555-0100",
    schema_version: 3,
    engine: { running: false, pid: null, status: "stopped" },
    heartbeat: null,
  };
  vi.spyOn(api, "config").mockImplementation(async () =>
    structuredClone(persisted),
  );
  vi.spyOn(api, "saveConfig").mockImplementation(async (patch) => {
    persisted = { ...persisted, ...patch };
    return structuredClone(persisted);
  });
  vi.spyOn(api, "state").mockImplementation(async () => structuredClone(state));
  vi.spyOn(api, "engine").mockImplementation(async (command) => {
    state = {
      ...state,
      engine:
        command === "stop"
          ? { running: false, pid: null, status: "stopped" }
          : { running: true, pid: 7, status: "running" },
      heartbeat: command === "stop" ? null : listening,
    };
  });
  vi.spyOn(api, "history").mockResolvedValue([]);
  vi.spyOn(api, "conversations").mockResolvedValue([]);
  vi.spyOn(api, "diagnostics").mockResolvedValue({ checks: [] });
  vi.spyOn(api, "autostart").mockResolvedValue({
    available: true,
    enabled: false,
  });
  vi.spyOn(api, "link").mockResolvedValue(undefined);
  vi.spyOn(api, "linkStatus").mockResolvedValue({ state: "starting" });
  vi.spyOn(api, "cancelLink").mockResolvedValue(undefined);
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
});

afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dark");
  window.history.replaceState({}, "", "/");
});

async function mount() {
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await screen.findByRole("navigation", { name: "Main navigation" });
}

function navigate(page: string) {
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).getByRole("button", {
      name: page,
    }),
  );
}

describe("engine summary", () => {
  // it.each tables are built before beforeEach runs, so use a standalone state.
  const base = (overrides: Partial<AppState>): AppState => ({
    linked: true,
    unlinked: false,
    account: "+1 555-555-0100",
    schema_version: 3,
    engine: { running: false, pid: null, status: "stopped" },
    heartbeat: null,
    ...overrides,
  });
  it.each([
    [base({ linked: false }), "Not linked"],
    [base({ unlinked: true }), "Not linked"],
    [
      base({ engine: { running: false, pid: null, status: "stopped" } }),
      "Paused",
    ],
    [
      base({ engine: { running: false, pid: null, status: "backoff" } }),
      "Restarting…",
    ],
    [
      base({
        engine: { running: true, pid: 1, status: "running" },
        heartbeat: null,
      }),
      "Starting…",
    ],
    [
      base({
        engine: { running: true, pid: 1, status: "running" },
        heartbeat: listening,
      }),
      "Listening",
    ],
    [
      base({
        engine: { running: true, pid: 1, status: "running" },
        heartbeat: {
          ...listening,
          active: { direction: "incoming", since: 1 },
        },
      }),
      "Transcribing…",
    ],
    [
      base({
        heartbeat: {
          ...listening,
          state: "needs_attention",
          detail: "Link again",
        },
      }),
      "Needs attention",
    ],
  ])("describes %# as %s", (value, label) => {
    expect(engineSummary(value, false).label).toBe(label);
  });
  it("reports a lost connection to the background service", () => {
    expect(engineSummary(undefined, true).label).toBe("Not connected");
  });
});

describe("application shell", () => {
  it("opens a deep-linked page without creating unsaved changes", async () => {
    window.history.replaceState({}, "", "/?page=Delivery");
    await mount();
    expect(
      screen.getByRole("heading", { level: 1, name: "Delivery" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it("asks to link first and opens the QR dialog", async () => {
    state.linked = false;
    await mount();
    expect(await screen.findByRole("button", { name: "Start" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Link Signal/ }));
    await waitFor(() => expect(api.link).toHaveBeenCalledOnce());
    expect(screen.getByText(/Preparing a link code/)).toBeInTheDocument();
  });

  it("explains when the phone removed this computer", async () => {
    state.unlinked = true;
    await mount();
    expect(
      await screen.findByText("Signal removed this computer"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Link again/ }),
    ).toBeInTheDocument();
  });

  it("shows what the engine reports", async () => {
    state.engine = { running: true, pid: 7, status: "running" };
    state.heartbeat = listening;
    await mount();
    expect(await screen.findByText(/small · ready/)).toBeInTheDocument();
    expect(screen.getByText("3 transcribed")).toBeInTheDocument();
    expect(screen.getAllByText("Listening").length).toBeGreaterThan(0);
  });

  it.each(["backoff", "unknown"])(
    "offers Pause while the engine status is %s",
    async (status) => {
      state.engine = { running: false, pid: null, status };
      await mount();
      const pause = await screen.findByRole("button", { name: "Pause" });
      fireEvent.click(pause);
      await waitFor(() =>
        expect(api.engine).toHaveBeenCalledExactlyOnceWith("stop"),
      );
      expect(
        await screen.findByRole("button", { name: "Start" }),
      ).toBeEnabled();
    },
  );

  it("keeps the reload warning until a successful pause", async () => {
    state.engine = { running: true, pid: 7, status: "running" };
    state.heartbeat = listening;
    vi.mocked(api.engine).mockRejectedValue(
      new Error("Process could not stop"),
    );
    await mount();
    navigate("Transcription");
    fireEvent.change(screen.getByLabelText("Whisper model"), {
      target: { value: "medium" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("alert");
    expect(api.engine).toHaveBeenCalledWith("restart");
    expect(persisted.transcription.model).toBe("medium");
    const warning = /It may still be using the previous settings/;
    fireEvent.click(
      screen.getByRole("button", { name: "Dismiss notification" }),
    );
    expect(screen.getByText(warning)).toBeInTheDocument();
    navigate("History");
    expect(screen.getByText(warning)).toBeInTheDocument();
    vi.mocked(api.engine).mockImplementation(async () => {
      state.engine = { running: false, pid: null, status: "stopped" };
    });
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await screen.findByRole("button", { name: "Start" });
    expect(screen.queryByText(warning)).not.toBeInTheDocument();
  });
});

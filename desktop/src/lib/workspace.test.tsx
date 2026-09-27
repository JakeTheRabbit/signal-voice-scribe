import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "./tauri";
import { WorkspaceProvider, useWorkspace } from "./workspace";
import type { AppConfig } from "./types";

const base: AppConfig = {
  schema_version: 3,
  transcription: {
    model: "small",
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
    retention_hours: 0,
    conversation_retention_hours: {},
    keep_audio: true,
  },
  desktop: { theme: "system", start_engine_on_launch: true },
  future: { keep: true },
};
const withModel = (config: AppConfig, model: string): AppConfig => ({
  ...config,
  transcription: { ...config.transcription, model },
});
const withTheme = (config: AppConfig, theme: "light" | "dark"): AppConfig => ({
  ...config,
  desktop: { ...config.desktop, theme },
});
let client: QueryClient;
function Probe() {
  const { config, saved, dirty, saving, update, save, discard, applyError } =
    useWorkspace();
  return (
    <>
      <output data-testid="draft">
        {config.desktop.theme}/{config.transcription.model}
      </output>
      <output data-testid="saved">
        {saved.desktop.theme}/{saved.transcription.model}
      </output>
      <output data-testid="status">
        {dirty ? "dirty" : "clean"}/{saving ? "saving" : "idle"}
      </output>
      <output data-testid="apply-error">{applyError}</output>
      <button
        onClick={() =>
          update({ desktop: { ...config.desktop, theme: "dark" } })
        }
      >
        Dark
      </button>
      <button
        onClick={() =>
          update({
            transcription: { ...config.transcription, model: "medium" },
          })
        }
      >
        Medium
      </button>
      <button
        onClick={() =>
          update({
            transcription: { ...config.transcription, model: "large-v3" },
          })
        }
      >
        Large
      </button>
      <button onClick={save}>Save</button>
      <button onClick={discard}>Discard</button>
    </>
  );
}
async function mount() {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>
    </QueryClientProvider>,
  );
  await screen.findByText("Dark");
}
beforeEach(() => {
  vi.spyOn(api, "config").mockResolvedValue(structuredClone(base));
  vi.spyOn(api, "saveConfig").mockImplementation(async (patch) => ({
    ...structuredClone(base),
    ...patch,
  }));
  vi.spyOn(api, "state").mockResolvedValue({
    linked: true,
    unlinked: false,
    account: "Demo",
    schema_version: 3,
    engine: { running: true, pid: 1, status: "running" },
    heartbeat: null,
  });
  vi.spyOn(api, "engine").mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
});
describe("workspace persistence", () => {
  it("edits remain drafts until save and discard restores the saved state", async () => {
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    expect(screen.getByTestId("status").textContent).toBe("dirty/idle");
    expect(api.saveConfig).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Discard"));
    expect(screen.getByTestId("draft").textContent).toBe("system/small");
  });
  it("saves appearance without restarting message processing", async () => {
    await mount();
    fireEvent.click(screen.getByText("Dark"));
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() =>
      expect(screen.getByTestId("status").textContent).toBe("clean/idle"),
    );
    expect(api.saveConfig).toHaveBeenCalledWith({
      desktop: { ...base.desktop, theme: "dark" },
    });
    expect(api.engine).not.toHaveBeenCalled();
  });
  it("restarts an already running engine after a processing change", async () => {
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    fireEvent.click(screen.getByText("Save"));
    await screen.findByText("Changes saved. Engine restarted.");
    expect(api.engine).toHaveBeenCalledWith("restart");
  });
  it("does not start a stopped engine when saving", async () => {
    vi.mocked(api.state).mockResolvedValue({
      linked: true,
      unlinked: false,
      account: "Demo",
      schema_version: 3,
      engine: { running: false, pid: null, status: "stopped" },
      heartbeat: null,
    });
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    fireEvent.click(screen.getByText("Save"));
    await screen.findByText("Changes saved.");
    expect(api.engine).not.toHaveBeenCalled();
  });
  it("keeps unsaved edits and reports a failed disk write", async () => {
    vi.mocked(api.saveConfig).mockRejectedValue(new Error("Disk full"));
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    fireEvent.click(screen.getByText("Save"));
    await screen.findByRole("alert");
    expect(screen.getByTestId("status").textContent).toBe("dirty/idle");
    expect(screen.getByTestId("saved").textContent).toBe("system/small");
    expect(api.engine).not.toHaveBeenCalled();
  });
  it("distinguishes a successful save from a failed restart", async () => {
    vi.mocked(api.engine).mockRejectedValue(new Error("Engine unavailable"));
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    fireEvent.click(screen.getByText("Save"));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Saved, but the engine could not restart",
    );
    expect(screen.getByTestId("saved").textContent).toBe("system/medium");
  });
  it("preserves further edits made while a save is in flight", async () => {
    let complete!: (config: AppConfig) => void;
    vi.mocked(api.saveConfig).mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    );
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    fireEvent.click(screen.getByText("Save"));
    fireEvent.click(screen.getByText("Large"));
    complete(withModel(base, "medium"));
    await waitFor(() =>
      expect(screen.getByTestId("status").textContent).toBe("dirty/idle"),
    );
    expect(screen.getByTestId("draft").textContent).toBe("system/large-v3");
    expect(screen.getByTestId("saved").textContent).toBe("system/medium");
  });
  it("syncs a pristine draft after refetch without creating edits to save", async () => {
    await mount();
    vi.mocked(api.config).mockResolvedValue(
      withTheme(withModel(base, "medium"), "light"),
    );
    await act(async () => {
      await client.refetchQueries({ queryKey: ["config"] });
    });
    await waitFor(() =>
      expect(screen.getByTestId("draft").textContent).toBe("light/medium"),
    );
    expect(screen.getByTestId("saved").textContent).toBe("light/medium");
    expect(screen.getByTestId("status").textContent).toBe("clean/idle");
    expect(api.saveConfig).not.toHaveBeenCalled();
    // A later user edit must not send the stale pre-refetch model back to disk.
    fireEvent.click(screen.getByText("Dark"));
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() =>
      expect(api.saveConfig).toHaveBeenCalledWith({
        desktop: { ...base.desktop, theme: "dark" },
      }),
    );
  });
  it("rebases a genuine edit over nonconflicting refreshed settings", async () => {
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    vi.mocked(api.config).mockResolvedValue(withTheme(base, "light"));
    await act(async () => {
      await client.refetchQueries({ queryKey: ["config"] });
    });
    await waitFor(() =>
      expect(screen.getByTestId("draft").textContent).toBe("light/medium"),
    );
    expect(screen.getByTestId("saved").textContent).toBe("light/small");
    expect(screen.getByTestId("status").textContent).toBe("dirty/idle");
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() =>
      expect(api.saveConfig).toHaveBeenCalledWith({
        transcription: { ...base.transcription, model: "medium" },
      }),
    );
  });
  it("blocks colliding unsaved edits until discard, then saves only reapplied edits", async () => {
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    vi.mocked(api.config).mockResolvedValue(withModel(base, "large-v3"));
    await act(async () => {
      await client.refetchQueries({ queryKey: ["config"] });
    });
    await screen.findByText(/Settings changed elsewhere/);
    expect(screen.getByTestId("draft").textContent).toBe("system/medium");
    expect(screen.getByTestId("saved").textContent).toBe("system/large-v3");
    fireEvent.click(screen.getByText("Save"));
    expect(api.saveConfig).not.toHaveBeenCalled();
    expect(api.engine).not.toHaveBeenCalled();
    expect(screen.getByTestId("status").textContent).toBe("dirty/idle");
    fireEvent.click(screen.getByText("Discard"));
    expect(screen.getByTestId("draft").textContent).toBe("system/large-v3");
    expect(screen.getByTestId("status").textContent).toBe("clean/idle");
    fireEvent.click(screen.getByText("Dark"));
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() =>
      expect(api.saveConfig).toHaveBeenCalledExactlyOnceWith({
        desktop: { ...base.desktop, theme: "dark" },
      }),
    );
  });
  it("keeps the apply failure after dismissing its toast and saving only appearance", async () => {
    vi.mocked(api.engine).mockRejectedValue(new Error("Engine unavailable"));
    await mount();
    fireEvent.click(screen.getByText("Medium"));
    fireEvent.click(screen.getByText("Save"));
    await screen.findByRole("alert");
    expect(screen.getByTestId("saved").textContent).toBe("system/medium");
    expect(screen.getByTestId("status").textContent).toBe("clean/idle");
    fireEvent.click(
      screen.getByRole("button", { name: "Dismiss notification" }),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByTestId("apply-error").textContent).toMatch(
      /previous settings/,
    );
    fireEvent.click(screen.getByText("Dark"));
    fireEvent.click(screen.getByText("Save"));
    await screen.findByText("Changes saved.");
    expect(screen.getByTestId("apply-error").textContent).toMatch(
      /previous settings/,
    );
    expect(api.engine).toHaveBeenCalledTimes(1);
    // Only a successful processing reload establishes that the error is resolved.
    vi.mocked(api.engine).mockResolvedValue(undefined);
    fireEvent.click(screen.getByText("Large"));
    fireEvent.click(screen.getByText("Save"));
    await screen.findByText("Changes saved. Engine restarted.");
    expect(screen.getByTestId("apply-error").textContent).toBe("");
  });
});

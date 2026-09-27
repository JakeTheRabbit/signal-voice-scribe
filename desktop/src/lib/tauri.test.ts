import { beforeEach, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { api } from "./tauri";

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => true,
  invoke: vi.fn(),
}));

beforeEach(() => vi.mocked(invoke).mockReset());

it.each([
  [() => api.linkStatus(), "link_status", {}],
  [() => api.cancelLink(), "link_cancel", {}],
  [() => api.clearHistory(), "history_clear", {}],
  [() => api.setAutostart(true), "autostart_set", { enabled: true }],
  [() => api.audio("f".repeat(32)), "history_audio", { id: "f".repeat(32) }],
  [() => api.engine("stop"), "engine_stop", {}],
])("calls the matching native command (%#)", async (call, command, args) => {
  vi.mocked(invoke).mockResolvedValueOnce(null);
  await call();
  expect(invoke).toHaveBeenCalledExactlyOnceWith(command, args);
});

import { describe, expect, it } from "vitest";
import { demoInvoke } from "./demo";
import type { AppState, HistoryItem, LinkStatus } from "./types";

describe("demo workspace", () => {
  it("uses only fictional, reserved phone numbers", async () => {
    const state = (await demoInvoke("app_state", {})) as AppState;
    expect(state.account).toMatch(/555-555-01\d\d/);
  });

  it("filters history like the real service", async () => {
    const all = (await demoInvoke("history_list", {
      filters: {},
    })) as HistoryItem[];
    const sent = (await demoInvoke("history_list", {
      filters: { direction: "outgoing" },
    })) as HistoryItem[];
    expect(all.length).toBeGreaterThan(sent.length);
    expect(sent.every((item) => item.direction === "outgoing")).toBe(true);
    const found = (await demoInvoke("history_list", {
      filters: { query: "bakery" },
    })) as HistoryItem[];
    expect(found).toHaveLength(1);
  });

  it("walks through linking and pausing", async () => {
    await demoInvoke("link_signal", {});
    expect(((await demoInvoke("link_status", {})) as LinkStatus).state).toBe(
      "starting",
    );
    await demoInvoke("link_cancel", {});
    expect(((await demoInvoke("link_status", {})) as LinkStatus).state).toBe(
      "idle",
    );
    await demoInvoke("engine_stop", {});
    expect(
      ((await demoInvoke("app_state", {})) as AppState).engine.running,
    ).toBe(false);
  });

  it("refuses commands the real app doesn't have", async () => {
    await expect(demoInvoke("provider_catalog", {})).rejects.toThrow(
      /does not support/,
    );
  });
});

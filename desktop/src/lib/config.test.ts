import { describe, expect, it } from "vitest";
import {
  configPatch,
  durationLabel,
  normalizeConfig,
  retentionLabel,
} from "./config";
import type { AppConfig } from "./types";

describe("settings helpers", () => {
  it("fills missing sections with defaults and keeps unknown ones", () => {
    const config = normalizeConfig({
      schema_version: 3,
      delivery: { mode: "chat" } as AppConfig["delivery"],
      future: { keep: true },
    });
    expect(config.delivery).toEqual({
      mode: "chat",
      notify: true,
      failure_notices: true,
    });
    expect(config.transcription.model).toBe("auto");
    expect(config.history.retention_hours).toBe(0);
    expect(config.future).toEqual({ keep: true });
  });

  it("rejects unreadable settings", () => {
    expect(() => normalizeConfig([] as unknown as AppConfig)).toThrow(
      /unreadable/,
    );
  });

  it("patches only the sections that changed", () => {
    const saved = normalizeConfig({ schema_version: 3 });
    const draft = {
      ...saved,
      desktop: { ...saved.desktop, theme: "dark" as const },
    };
    expect(configPatch(saved, draft)).toEqual({ desktop: draft.desktop });
    expect(configPatch(saved, structuredClone(saved))).toEqual({});
  });

  it.each([
    [0, "Not kept"],
    [-1, "Until you delete it"],
    [1, "1 hour"],
    [24, "1 day"],
    [168, "7 days"],
    [36, "36 hours"],
  ])("labels %s hours as %s", (hours, label) => {
    expect(retentionLabel(hours)).toBe(label);
  });

  it("formats durations", () => {
    expect(durationLabel(83.4)).toBe("1:23");
    expect(durationLabel(0)).toBe("0:00");
    expect(durationLabel(null)).toBe("");
  });
});

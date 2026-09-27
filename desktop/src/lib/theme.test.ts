import { describe, expect, it, vi } from "vitest";
Object.defineProperty(globalThis, "matchMedia", {
  value: vi.fn(() => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })),
});
import { resolveTheme } from "./theme";
describe("theme", () => {
  it("follows system", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
  it("honours overrides", () =>
    expect(resolveTheme("dark", false)).toBe("dark"));
});

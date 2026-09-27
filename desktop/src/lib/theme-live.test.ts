import { afterEach, describe, expect, it, vi } from "vitest";
import { applyTheme } from "./theme";
afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.classList.remove("dark");
});
describe("live operating system appearance", () => {
  it("responds to a system theme change and removes its listener on cleanup", () => {
    const media = {
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => media),
    );
    const cleanup = applyTheme("system");
    expect(document.documentElement.style.colorScheme).toBe("light");
    media.matches = true;
    media.addEventListener.mock.calls[0][1]();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    cleanup();
    expect(media.removeEventListener).toHaveBeenCalledWith(
      "change",
      media.addEventListener.mock.calls[0][1],
    );
    vi.unstubAllGlobals();
  });
  it("keeps an explicit light override when the OS changes", () => {
    const media = {
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => media),
    );
    const cleanup = applyTheme("light");
    media.matches = true;
    media.addEventListener.mock.calls[0][1]();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    cleanup();
    vi.unstubAllGlobals();
  });
});

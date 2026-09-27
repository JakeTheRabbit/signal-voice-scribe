import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/tauri";
import { normalizeConfig } from "../../lib/config";
import type { AppConfig, Page } from "../../lib/types";
import { SettingsPages } from "../settings-pages";

let config: AppConfig;
const update = vi.fn((patch: Partial<AppConfig>) => {
  config = { ...config, ...patch };
});
const notice = vi.fn();
vi.mock("../../lib/workspace", () => ({
  useWorkspace: () => ({ config, update, notice, saving: false }),
}));

beforeEach(() => {
  config = normalizeConfig({ schema_version: 3 });
  vi.spyOn(api, "autostart").mockResolvedValue({
    available: true,
    enabled: false,
  });
  vi.spyOn(api, "setAutostart").mockImplementation(async (enabled) => ({
    available: true,
    enabled,
  }));
  vi.spyOn(api, "state").mockRejectedValue(new Error("not needed"));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  update.mockClear();
  notice.mockClear();
});

function Harness({ page }: { page: Page }) {
  const [, rerender] = useState(0);
  update.mockImplementation((patch) => {
    config = { ...config, ...patch };
    rerender((n) => n + 1);
  });
  return <SettingsPages page={page} />;
}

function mount(page: Page) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Harness page={page} />
    </QueryClientProvider>,
  );
}

describe("Transcription settings", () => {
  it("changes the model, language and which notes are transcribed", () => {
    mount("Transcription");
    fireEvent.change(screen.getByLabelText("Whisper model"), {
      target: { value: "medium" },
    });
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "de" },
    });
    fireEvent.click(screen.getByRole("switch", { name: "Group chats" }));
    expect(config.transcription).toMatchObject({
      model: "medium",
      language: "de",
      groups: false,
    });
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "" },
    });
    expect(config.transcription.language).toBeNull();
  });

  it("warns when nothing would be transcribed", () => {
    mount("Transcription");
    fireEvent.click(
      screen.getByRole("switch", { name: "Voice notes I receive" }),
    );
    fireEvent.click(screen.getByRole("switch", { name: "Voice notes I send" }));
    expect(screen.getByText(/nothing will be transcribed/)).toBeInTheDocument();
  });

  it("keeps an unusual language code visible", () => {
    config = normalizeConfig({
      schema_version: 3,
      transcription: { ...config.transcription, language: "xx" },
    });
    mount("Transcription");
    expect(
      screen.getByRole("option", { name: "Other: xx" }),
    ).toBeInTheDocument();
  });
});

describe("Delivery settings", () => {
  it("only posts into chats after confirmation", () => {
    mount("Delivery");
    fireEvent.click(screen.getByRole("radio", { name: /In the same chat/ }));
    expect(config.delivery.mode).toBe("note_to_self");
    fireEvent.click(screen.getByRole("button", { name: "Post in the chat" }));
    expect(config.delivery.mode).toBe("chat");
  });
});

describe("App settings", () => {
  it("turns start at login on through the app, immediately", async () => {
    mount("App");
    const toggle = await screen.findByRole("switch", {
      name: "Start at login",
    });
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    await waitFor(() => expect(api.setAutostart).toHaveBeenCalledWith(true));
    expect(notice).toHaveBeenCalledWith(
      "Signal Scribe will start when you log in.",
    );
  });
});

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
import { LinkDialog } from "./link-dialog";
import { api } from "../lib/tauri";
import type { LinkStatus } from "../lib/types";

let status: LinkStatus;
const onOpenChange = vi.fn();

beforeEach(() => {
  status = { state: "starting" };
  vi.spyOn(api, "link").mockResolvedValue(undefined);
  vi.spyOn(api, "linkStatus").mockImplementation(async () => status);
  vi.spyOn(api, "cancelLink").mockResolvedValue(undefined);
  vi.spyOn(api, "engine").mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  onOpenChange.mockClear();
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <LinkDialog open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
}

describe("linking dialog", () => {
  it("starts linking once and shows the QR code when it is ready", async () => {
    mount();
    await waitFor(() => expect(api.link).toHaveBeenCalledOnce());
    status = { state: "waiting", qr: "data:image/png;base64,AAAA" };
    const image = await screen.findByAltText(
      "QR code for linking Signal",
      {},
      { timeout: 3000 },
    );
    expect(image).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText(/Link new device/)).toBeInTheDocument();
  });

  it("offers to start transcribing after linking", async () => {
    status = { state: "linked", account: "+1 555-555-0100" };
    mount();
    fireEvent.click(
      await screen.findByRole(
        "button",
        { name: "Start transcribing" },
        { timeout: 3000 },
      ),
    );
    await waitFor(() => expect(api.engine).toHaveBeenCalledWith("start"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("explains an expired code and can get a new one", async () => {
    status = { state: "failed", reason: "expired" };
    mount();
    expect(
      await screen.findByText(/The code expired/, {}, { timeout: 3000 }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Get a new code/ }));
    await waitFor(() => expect(api.link).toHaveBeenCalledTimes(2));
  });

  it("cancels linking when closed while a code is showing", async () => {
    mount();
    status = { state: "waiting", qr: "data:image/png;base64,AAAA" };
    await screen.findByAltText(
      "QR code for linking Signal",
      {},
      { timeout: 3000 },
    );
    fireEvent.keyDown(document.activeElement || document.body, {
      key: "Escape",
    });
    await waitFor(() => expect(api.cancelLink).toHaveBeenCalledOnce());
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

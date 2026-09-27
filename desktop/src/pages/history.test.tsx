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
import { api } from "../lib/tauri";
import { HistoryPage } from "./history";
import type { HistoryItem } from "../lib/types";

const update = vi.fn();
const notice = vi.fn();
vi.mock("../lib/workspace", () => ({
  useWorkspace: () => ({
    config: {
      history: {
        retention_hours: 24,
        conversation_retention_hours: { Alex: 1 },
        keep_audio: true,
      },
    },
    update,
    notice,
  }),
}));
let client: QueryClient;
let entries: HistoryItem[];
beforeEach(() => {
  entries = [
    {
      id: "one",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      direction: "incoming",
      kind: "voice",
      conversation: "Alex",
      sender: "Alex",
      transcript: "A fictional retained transcript",
      duration: 12,
      language: "en",
      media_available: true,
    },
    {
      id: "expired",
      created_at: new Date(Date.now() - 7200000).toISOString(),
      expires_at: new Date(Date.now() - 1000).toISOString(),
      direction: "outgoing",
      kind: "voice",
      conversation: "Sam",
      sender: "You",
      transcript: "This expired transcript must not appear",
      duration: null,
      language: null,
      media_available: false,
    },
  ];
  vi.spyOn(api, "history").mockImplementation(async () => entries);
  vi.spyOn(api, "conversations").mockResolvedValue(["Alex", "Sam"]);
  vi.spyOn(api, "audio").mockResolvedValue({
    data_url: "data:audio/wav;base64,UklGRg==",
  });
  vi.spyOn(api, "deleteHistory").mockImplementation(async (ids) => {
    entries = entries.filter((item) => !ids.includes(item.id));
    return { deleted: ids.length };
  });
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
  update.mockClear();
  notice.mockClear();
});
async function mount() {
  render(
    <QueryClientProvider client={client}>
      <HistoryPage />
    </QueryClientProvider>,
  );
  await screen.findByText("1 result");
}
async function select() {
  fireEvent.click(screen.getByRole("button", { name: /Alex.*fictional/ }));
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function confirmDelete() {
  fireEvent.click(
    screen.getByRole("button", { name: "Delete selected message" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Delete from this computer" }),
  );
}
describe("history workspace", () => {
  it("never renders expired records returned by a stale query", async () => {
    await mount();
    expect(
      screen.queryByText("This expired transcript must not appear"),
    ).toBeNull();
  });
  it("passes the user's search and filters to the native API", async () => {
    await mount();
    fireEvent.change(screen.getByLabelText("Search history"), {
      target: { value: "fictional" },
    });
    fireEvent.change(screen.getByLabelText("Filter direction"), {
      target: { value: "incoming" },
    });
    fireEvent.change(screen.getByLabelText("Filter conversation"), {
      target: { value: "Alex" },
    });
    await waitFor(() =>
      expect(api.history).toHaveBeenLastCalledWith({
        query: "fictional",
        direction: "incoming",
        conversation: "Alex",
        limit: 1000,
      }),
    );
  });
  it("loads audio only on replay and clears it when details close", async () => {
    await mount();
    await select();
    expect(api.audio).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Replay audio" }));
    await waitFor(() =>
      expect(document.querySelector("audio")?.getAttribute("src")).toBe(
        "data:audio/wav;base64,UklGRg==",
      ),
    );
    expect(api.audio).toHaveBeenCalledWith("one");
    fireEvent.click(screen.getByRole("button", { name: "Close details" }));
    expect(document.querySelector("audio")).toBeNull();
  });
  it("rejects external audio URLs and reports the failure", async () => {
    vi.mocked(api.audio).mockResolvedValue({
      data_url: "https://example.com/private-recording",
    });
    await mount();
    await select();
    fireEvent.click(screen.getByRole("button", { name: "Replay audio" }));
    await waitFor(() =>
      expect(notice).toHaveBeenCalledWith(
        "The retained audio format is unsupported.",
        true,
      ),
    );
    expect(document.querySelector("audio")).toBeNull();
  });
  it("requires confirmation and deletes only the selected local record", async () => {
    await mount();
    await select();
    fireEvent.click(
      screen.getByRole("button", { name: "Delete selected message" }),
    );
    expect(api.deleteHistory).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(api.deleteHistory).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Delete selected message" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Delete from this computer" }),
    );
    await waitFor(() =>
      expect(api.deleteHistory).toHaveBeenCalledWith(["one"]),
    );
    await screen.findByText("No transcripts yet");
  });
  it("removing a conversation override sends an empty replacement map", async () => {
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Auto-delete" }));
    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove retention override for Alex",
      }),
    );
    expect(update).toHaveBeenCalledWith({
      history: {
        retention_hours: 24,
        conversation_retention_hours: {},
        keep_audio: true,
      },
    });
  });
  it("evicts a successfully deleted record from every history cache before a failed refetch settles", async () => {
    await mount();
    // Inactive overview and filtered histories must be scrubbed too, without
    // dropping other retained records that were not selected for deletion.
    client.setQueryDefaults(["history"], { gcTime: Infinity });
    const survivor = {
      ...entries[0],
      id: "survivor",
      transcript: "Keep this record",
    };
    const recentKey = ["history", "recent"];
    const filteredKey = ["history", "fictional", "incoming", "Alex"];
    for (const key of [recentKey, filteredKey]) {
      client.setQueryData(key, [entries[0], survivor]);
    }
    const refresh = deferred<HistoryItem[]>();
    vi.mocked(api.history).mockReturnValue(refresh.promise);
    await select();
    confirmDelete();
    await waitFor(() => expect(api.history).toHaveBeenCalledTimes(2));
    expect(api.deleteHistory).toHaveBeenCalledExactlyOnceWith(["one"]);
    await waitFor(() =>
      expect(
        screen.queryAllByText("A fictional retained transcript"),
      ).toHaveLength(0),
    );
    expect(screen.queryByRole("button", { name: "Close details" })).toBeNull();
    for (const key of [recentKey, filteredKey]) {
      expect(
        client.getQueryData<HistoryItem[]>(key)?.map((item) => item.id),
      ).toEqual(["survivor"]);
    }
    for (const [, cached] of client.getQueriesData<HistoryItem[]>({
      queryKey: ["history"],
    })) {
      expect(cached?.some((item) => item.id === "one")).toBe(false);
    }
    await act(async () => {
      refresh.reject(new Error("History refresh unavailable"));
      await refresh.promise.catch(() => {});
    });
    await screen.findByText(/History refresh unavailable/);
    expect(
      screen.queryAllByText("A fictional retained transcript"),
    ).toHaveLength(0);
    expect(document.querySelector("audio")).toBeNull();
    await waitFor(() =>
      expect(notice).toHaveBeenCalledWith(
        "1 history item deleted from this computer.",
      ),
    );
  });

  it("cancels an older history fetch so its late result cannot restore deleted plaintext", async () => {
    await mount();
    const staleEntries = structuredClone(entries);
    const staleFetch = deferred<HistoryItem[]>();
    vi.mocked(api.history).mockReturnValueOnce(staleFetch.promise);
    let pending!: Promise<void>;
    act(() => {
      pending = client.refetchQueries({ queryKey: ["history"] });
    });
    await select();
    confirmDelete();
    await screen.findByText("No transcripts yet");
    await act(async () => {
      staleFetch.resolve(staleEntries);
      await pending;
    });
    expect(
      screen.queryAllByText("A fictional retained transcript"),
    ).toHaveLength(0);
    for (const [, cached] of client.getQueriesData<HistoryItem[]>({
      queryKey: ["history"],
    })) {
      expect(cached?.some((item) => item.id === "one")).toBe(false);
    }
  });

  it("ignores deleted-message audio arriving after a different message has started replaying", async () => {
    await mount();
    const lateAudio = deferred<{ data_url: string }>();
    vi.mocked(api.audio).mockReturnValueOnce(lateAudio.promise);
    await select();
    fireEvent.click(screen.getByRole("button", { name: "Replay audio" }));
    expect(api.audio).toHaveBeenCalledWith("one");
    expect(
      screen
        .getByRole("button", { name: "Loading audio…" })
        .hasAttribute("disabled"),
    ).toBe(true);
    const survivor = {
      ...entries[0],
      id: "two",
      conversation: "Sam",
      transcript: "A different retained message",
    };
    entries = [...entries, survivor];
    confirmDelete();
    await screen.findByRole("button", {
      name: /Sam.*different retained message/,
    });
    expect(document.querySelector("audio")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: /Sam.*different retained message/ }),
    );
    const currentAudio = "data:audio/wav;base64,Q1VSUkVOVA==";
    vi.mocked(api.audio).mockResolvedValue({ data_url: currentAudio });
    fireEvent.click(screen.getByRole("button", { name: "Replay audio" }));
    await waitFor(() =>
      expect(document.querySelector("audio")?.getAttribute("src")).toBe(
        currentAudio,
      ),
    );
    await act(async () => {
      lateAudio.resolve({ data_url: "data:audio/wav;base64,REVMRVRFRA==" });
      await lateAudio.promise;
    });
    expect(document.querySelector("audio")?.getAttribute("src")).toBe(
      currentAudio,
    );
    expect(
      screen.queryAllByText("A fictional retained transcript"),
    ).toHaveLength(0);
    expect(api.audio).toHaveBeenLastCalledWith("two");
  });
});

describe("history clearing", () => {
  it("deletes everything only after a second confirmation", async () => {
    vi.spyOn(api, "clearHistory").mockImplementation(async () => {
      const deleted = entries.length;
      entries = [];
      return { deleted };
    });
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Delete all history" }));
    expect(api.clearHistory).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete everything" }));
    await waitFor(() => expect(api.clearHistory).toHaveBeenCalledOnce());
    await screen.findByText("No transcripts yet");
  });
  it("shows who sent a note and how long it was", async () => {
    await mount();
    expect(screen.getByText(/From Alex · 0:12/)).toBeTruthy();
  });
});

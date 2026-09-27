import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Clock3,
  Copy,
  FileText,
  Search,
  SlidersHorizontal,
  Trash2,
  Volume2,
  X,
} from "lucide-react";
import { api, errorMessage, isDemo } from "../lib/tauri";
import { useWorkspace } from "../lib/workspace";
import { Button } from "../components/ui/button";
import { Dialog } from "../components/ui/dialog";
import {
  EmptyState,
  Field,
  InfoNote,
  ToggleField,
} from "../components/settings";
import { durationLabel } from "../lib/config";
import type { HistoryItem } from "../lib/types";

export const retentionOptions = [
  [0, "Don’t keep history"],
  [1, "1 hour"],
  [24, "24 hours"],
  [168, "7 days"],
  [720, "30 days"],
  [-1, "Until I delete it"],
] as const;
function expiresLabel(item: HistoryItem) {
  if (!item.expires_at) return "No automatic expiry";
  const ms = Date.parse(item.expires_at) - Date.now();
  return ms <= 0
    ? "Expired"
    : ms < 3600000
      ? `Deletes in ${Math.max(1, Math.ceil(ms / 60000))} min`
      : ms < 48 * 3600000
        ? `Deletes in ${Math.ceil(ms / 3600000)} h`
        : `Deletes in ${Math.round(ms / 86400000)} days`;
}
export function HistoryPage() {
  const { config, update, notice } = useWorkspace();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [direction, setDirection] = useState("");
  const [conversation, setConversation] = useState("");
  const [period, setPeriod] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [retentionOpen, setRetentionOpen] = useState(false);
  const [deleteIds, setDeleteIds] = useState<string[]>([]);
  const [clearOpen, setClearOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [audio, setAudio] = useState<{ id: string; url: string } | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const replayGeneration = useRef(0);
  const [overrideChat, setOverrideChat] = useState("");
  const [overrideHours, setOverrideHours] = useState(24);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query), 250);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const history = useQuery({
    queryKey: ["history", debounced, direction, conversation],
    queryFn: () =>
      api.history({
        query: debounced,
        direction,
        conversation,
        limit: 1000,
      }),
    refetchInterval: 15000,
    retry: false,
  });
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: api.conversations,
    retry: false,
  });
  const items = (history.data || []).filter(
    (item) =>
      (!item.expires_at || Date.parse(item.expires_at) > now) &&
      (period === "all" ||
        Date.parse(item.created_at) >= now - Number(period) * 86400000),
  );
  const selected = items.find((i) => i.id === selectedId);
  const overrides = config.history?.conversation_retention_hours || {};
  const filtering = !!(query || direction || conversation || period !== "all");
  useEffect(() => {
    replayGeneration.current += 1;
    setAudio(null);
    setLoadingAudio(false);
  }, [selectedId]);
  useEffect(() => {
    if (!selected) setAudio(null);
  }, [selected?.id]);
  async function remove() {
    setDeleting(true);
    try {
      const result = await api.deleteHistory(deleteIds);
      replayGeneration.current += 1;
      await queryClient.cancelQueries({ queryKey: ["history"] });
      const removed = new Set(deleteIds);
      queryClient.setQueriesData<HistoryItem[]>(
        { queryKey: ["history"] },
        (old) => old?.filter((item) => !removed.has(item.id)),
      );
      setDeleteIds([]);
      setSelectedId(null);
      setAudio(null);
      await queryClient.invalidateQueries({ queryKey: ["history"] });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      notice(
        `${result.deleted} history item${result.deleted === 1 ? "" : "s"} deleted from this computer.`,
      );
    } catch (error) {
      notice(errorMessage(error), true);
    } finally {
      setDeleting(false);
    }
  }
  async function clearAll() {
    setDeleting(true);
    try {
      const result = await api.clearHistory();
      replayGeneration.current += 1;
      setSelectedId(null);
      setAudio(null);
      setClearOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["history"] });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      notice(
        `Deleted ${result.deleted} item${result.deleted === 1 ? "" : "s"} from this computer.`,
      );
    } catch (error) {
      notice(errorMessage(error), true);
    } finally {
      setDeleting(false);
    }
  }
  async function replay(item: HistoryItem) {
    const generation = ++replayGeneration.current;
    setLoadingAudio(true);
    try {
      const result = await api.audio(item.id);
      if (!/^data:audio\//.test(result.data_url))
        throw new Error("The retained audio format is unsupported.");
      if (
        generation === replayGeneration.current &&
        (!item.expires_at || Date.parse(item.expires_at) > Date.now())
      )
        setAudio({ id: item.id, url: result.data_url });
    } catch (error) {
      notice(errorMessage(error), true);
    } finally {
      if (generation === replayGeneration.current) setLoadingAudio(false);
    }
  }
  return (
    <div className="stack">
      <div className="history-toolbar">
        <div className="search-input">
          <Search size={17} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search transcripts or people…"
            aria-label="Search history"
          />
          {query && (
            <button aria-label="Clear search" onClick={() => setQuery("")}>
              <X size={15} />
            </button>
          )}
        </div>
        <Button variant="outline" onClick={() => setRetentionOpen(true)}>
          <Clock3 size={16} />
          Auto-delete
        </Button>
      </div>
      <div className="filter-row">
        <SlidersHorizontal size={16} />
        <select
          className="filter-select"
          aria-label="Filter conversation"
          value={conversation}
          onChange={(e) => setConversation(e.target.value)}
        >
          <option value="">All conversations</option>
          {conversations.data?.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <select
          className="filter-select"
          aria-label="Filter direction"
          value={direction}
          onChange={(e) => setDirection(e.target.value)}
        >
          <option value="">Sent & received</option>
          <option value="incoming">Received</option>
          <option value="outgoing">Sent by me</option>
        </select>
        <select
          className="filter-select"
          aria-label="Filter time"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
        >
          <option value="all">Any time</option>
          <option value="1">Last 24 hours</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
        </select>
        {filtering && (
          <button
            className="text-action"
            onClick={() => {
              setQuery("");
              setDirection("");
              setConversation("");
              setPeriod("all");
            }}
          >
            Reset filters
          </button>
        )}
      </div>
      {history.isError && (
        <InfoNote warning>
          {errorMessage(history.error)}{" "}
          <button className="text-action" onClick={() => history.refetch()}>
            Try again
          </button>
        </InfoNote>
      )}
      <div className="history-workspace">
        <section className="history-list" aria-label="Transcription history">
          <div className="history-list-heading">
            <span>
              {history.isPending
                ? "Loading…"
                : `${items.length} result${items.length === 1 ? "" : "s"}`}
              {items.length === 1000 ? " (latest 1,000)" : ""}
            </span>
            {items.length > 0 && (
              <button
                className="text-action danger-text"
                onClick={() => setDeleteIds(items.map((i) => i.id))}
              >
                Delete results
              </button>
            )}
          </div>
          {items.length
            ? items.map((item) => (
                <button
                  key={item.id}
                  className={`history-item ${selectedId === item.id ? "selected" : ""}`}
                  onClick={() => setSelectedId(item.id)}
                  aria-pressed={selectedId === item.id}
                >
                  <span className="contact-avatar">
                    {item.conversation.charAt(0).toUpperCase()}
                  </span>
                  <div className="history-item-body">
                    <div className="recent-meta">
                      <strong>
                        {item.conversation || "Signal conversation"}
                      </strong>
                      <time>
                        {new Date(item.created_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </time>
                    </div>
                    <p>{item.transcript}</p>
                    <div className="history-item-footer">
                      <span className="direction">
                        {item.direction === "incoming" ? (
                          <ArrowDownLeft size={12} />
                        ) : (
                          <ArrowUpRight size={12} />
                        )}{" "}
                        {item.direction === "incoming"
                          ? `From ${item.sender}`
                          : "You sent"}
                        {item.duration
                          ? ` · ${durationLabel(item.duration)}`
                          : ""}
                      </span>
                      <span>{expiresLabel(item)}</span>
                    </div>
                  </div>
                </button>
              ))
            : !history.isPending &&
              !history.isError && (
                <EmptyState
                  title={
                    filtering
                      ? "No matching transcripts"
                      : config.history.retention_hours
                        ? "No transcripts yet"
                        : "History is off"
                  }
                  description={
                    filtering
                      ? "Try another search or reset the filters."
                      : config.history.retention_hours
                        ? "New voice notes appear here once they're transcribed."
                        : "Transcripts only go to Signal. Choose how long to keep a searchable copy on this computer."
                  }
                >
                  {!filtering && !config.history.retention_hours && (
                    <Button
                      variant="outline"
                      onClick={() => setRetentionOpen(true)}
                    >
                      Keep history
                    </Button>
                  )}
                </EmptyState>
              )}
        </section>
        <section className="history-detail" aria-label="Message details">
          {selected ? (
            <>
              <div className="detail-heading">
                <span className="contact-avatar">
                  {selected.conversation.charAt(0).toUpperCase()}
                </span>
                <div>
                  <h2>{selected.conversation}</h2>
                  <p>{new Date(selected.created_at).toLocaleString()}</p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Close details"
                  onClick={() => setSelectedId(null)}
                >
                  <X size={17} />
                </Button>
              </div>
              <span className="pill off">
                <FileText size={13} />
                {selected.direction === "incoming"
                  ? `From ${selected.sender}`
                  : "You sent"}
                {selected.duration
                  ? ` · ${durationLabel(selected.duration)}`
                  : ""}
                {selected.language && selected.language !== "en"
                  ? ` · ${selected.language}`
                  : ""}
              </span>
              <blockquote>{selected.transcript}</blockquote>
              <div className="inline-actions">
                <Button
                  variant="outline"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(selected.transcript);
                      notice("Transcript copied.");
                    } catch {
                      notice("Clipboard is unavailable.", true);
                    }
                  }}
                >
                  <Copy size={15} />
                  Copy text
                </Button>
                <Button
                  variant="ghost"
                  aria-label="Delete selected message"
                  onClick={() => setDeleteIds([selected.id])}
                >
                  <Trash2 size={16} />
                </Button>
              </div>
              <div className="audio-section">
                <h3>Original audio</h3>
                {audio?.id === selected.id ? (
                  <>
                    <audio controls autoPlay src={audio.url} />
                    {isDemo && (
                      <small className="subtle">
                        A generated tone plays in the demo.
                      </small>
                    )}
                  </>
                ) : (
                  <Button
                    variant="outline"
                    disabled={!selected.media_available || loadingAudio}
                    onClick={() => replay(selected)}
                  >
                    <Volume2 size={16} />
                    {loadingAudio
                      ? "Loading audio…"
                      : selected.media_available
                        ? "Replay audio"
                        : "Audio not kept"}
                  </Button>
                )}
              </div>
              <div className="expiry-note">
                <Clock3 size={15} />
                <span>
                  {expiresLabel(selected)}
                  {selected.expires_at && (
                    <small>
                      {new Date(selected.expires_at).toLocaleString()}
                    </small>
                  )}
                </span>
              </div>
            </>
          ) : (
            <div className="detail-placeholder">
              <FileText size={32} />
              <h2>Every word, at a glance.</h2>
              <p>
                Select a transcript to read it in full, copy the text, or replay
                the audio when you're somewhere you can listen.
              </p>
              <span className="pill off">
                <Clock3 size={13} />
                You control what stays
              </span>
            </div>
          )}
        </section>
      </div>
      <p className="footnote">
        This history is Signal Scribe's own copy on this computer, separate from
        your chats in Signal. Deleting here doesn't touch Signal, and backups or
        SSD remnants are outside Signal Scribe's control.{" "}
        {config.history.retention_hours !== 0 && (
          <button
            className="text-action danger-text"
            onClick={() => setClearOpen(true)}
          >
            Delete all history
          </button>
        )}
      </p>
      <Dialog
        open={retentionOpen}
        onOpenChange={setRetentionOpen}
        title="Keep history"
        description="How long transcripts (and their audio) stay on this computer. Off by default."
      >
        <Field
          label="Default retention"
          description="Changes apply to new entries. Existing entries keep their expiry time."
        >
          <select
            className="field-select"
            aria-label="Default retention"
            value={config.history?.retention_hours || 0}
            onChange={(e) =>
              update({
                history: {
                  ...config.history,
                  retention_hours: Number(e.target.value),
                },
              })
            }
          >
            {!retentionOptions.some(
              ([hours]) => hours === (config.history?.retention_hours || 0),
            ) && (
              <option value={config.history?.retention_hours}>
                {config.history?.retention_hours} hours
              </option>
            )}
            {retentionOptions.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <ToggleField
          label="Keep the audio for replay"
          description="Store a copy of each voice note with its transcript. Off keeps text only."
          checked={config.history.keep_audio}
          onChange={(keep_audio) =>
            update({ history: { ...config.history, keep_audio } })
          }
        />
        <h3 className="dialog-subheading">Different period for some chats</h3>
        {Object.entries(overrides).map(([chat, hours]) => (
          <div className="list-item" key={chat}>
            <span>{chat}</span>
            <span>
              {retentionOptions.find((o) => o[0] === hours)?.[1] ||
                `${hours} hours`}
            </span>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove retention override for ${chat}`}
              onClick={() => {
                const next = { ...overrides };
                delete next[chat];
                update({
                  history: {
                    ...config.history,
                    conversation_retention_hours: next,
                  },
                });
              }}
            >
              <X size={15} />
            </Button>
          </div>
        ))}
        <div className="stack">
          <label className="field-label" htmlFor="retention-chat">
            Conversation
          </label>
          <input
            id="retention-chat"
            className="field-input"
            placeholder="Chat name, e.g. Book club"
            list="known-conversations"
            value={overrideChat}
            onChange={(e) => setOverrideChat(e.target.value)}
          />
          <datalist id="known-conversations">
            {conversations.data?.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
          <select
            className="field-select"
            aria-label="Conversation retention"
            value={overrideHours}
            onChange={(e) => setOverrideHours(Number(e.target.value))}
          >
            {retentionOptions.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
          <Button
            variant="outline"
            disabled={!overrideChat.trim()}
            onClick={() => {
              update({
                history: {
                  ...config.history,
                  conversation_retention_hours: {
                    ...overrides,
                    [overrideChat.trim()]: overrideHours,
                  },
                },
              });
              setOverrideChat("");
            }}
          >
            Add override
          </Button>
        </div>
        <div className="dialog-actions">
          <Button onClick={() => setRetentionOpen(false)}>Done</Button>
        </div>
        <p className="footnote">Use Save changes to apply these settings.</p>
      </Dialog>
      <Dialog
        open={deleteIds.length > 0}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteIds([]);
        }}
        title={`Delete ${deleteIds.length} history item${deleteIds.length === 1 ? "" : "s"}?`}
        description="This removes the selected transcripts and their audio from this computer. It can't be undone. Your chats in Signal are not affected."
      >
        <div className="dialog-actions">
          <Button
            variant="outline"
            disabled={deleting}
            onClick={() => setDeleteIds([])}
          >
            Cancel
          </Button>
          <Button variant="destructive" disabled={deleting} onClick={remove}>
            {deleting ? "Deleting…" : "Delete from this computer"}
          </Button>
        </div>
      </Dialog>
      <Dialog
        open={clearOpen}
        onOpenChange={(open) => {
          if (!deleting) setClearOpen(open);
        }}
        title="Delete all history?"
        description="Every transcript and saved audio file is removed from this computer. It can't be undone. Your chats in Signal are not affected."
      >
        <div className="dialog-actions">
          <Button
            variant="outline"
            disabled={deleting}
            onClick={() => setClearOpen(false)}
          >
            Cancel
          </Button>
          <Button variant="destructive" disabled={deleting} onClick={clearAll}>
            {deleting ? "Deleting…" : "Delete everything"}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

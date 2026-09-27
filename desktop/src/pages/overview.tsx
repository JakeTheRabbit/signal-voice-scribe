import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownLeft,
  ArrowUpRight,
  AudioLines,
  ChevronRight,
  Cpu,
  FileText,
  Link2,
  LockKeyhole,
  RadioTower,
  ShieldCheck,
  Smartphone,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { InfoNote } from "../components/settings";
import { LinkDialog } from "../components/link-dialog";
import { useWorkspace } from "../lib/workspace";
import { api, errorMessage, isDemo } from "../lib/tauri";
import { durationLabel, retentionLabel } from "../lib/config";
import type { AppState, Page } from "../lib/types";

function since(seconds: number | null | undefined): string {
  if (!seconds) return "";
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - seconds) / 60));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

export function Overview({
  navigate,
  state,
  stateError,
}: {
  navigate: (page: Page) => void;
  state?: AppState;
  stateError: unknown;
}) {
  const { saved: config } = useWorkspace();
  const [linking, setLinking] = useState(false);
  useEffect(() => {
    if (isDemo && new URLSearchParams(location.search).get("dialog") === "link")
      setLinking(true);
  }, []);
  const hours = config.history.retention_hours;
  const recent = useQuery({
    queryKey: ["history", "recent"],
    queryFn: () => api.history({ limit: 4 }),
    refetchInterval: 10000,
    retry: false,
    enabled: hours !== 0,
  });
  const beat =
    state?.heartbeat && !state.heartbeat.stale ? state.heartbeat : null;
  const running = !!state?.engine.running;
  const model = beat?.model;
  const needsLink = !!state && (!state.linked || state.unlinked);
  const inChat = config.delivery.mode === "chat";
  const today = beat?.queue?.today || {};
  const pending = beat?.queue?.pending || 0;

  return (
    <div className="stack overview">
      <div className="overview-heading">
        <div>
          <span className="quiet-label">Signal Scribe</span>
          <h1>
            {needsLink
              ? "Read voice notes instead of listening."
              : running
                ? "Your next voice note will arrive as text."
                : "Transcription is paused."}
          </h1>
          <p>
            {needsLink
              ? "Link your Signal account and every voice note becomes something you can read, wherever you are."
              : "Voice notes you receive and send are turned into text on this computer."}
          </p>
        </div>
        <span className="pill local">
          <LockKeyhole size={13} />
          On-device
        </span>
      </div>

      {state?.startup_error && (
        <InfoNote warning>{state.startup_error.message}</InfoNote>
      )}
      {stateError ? (
        <InfoNote warning>
          {errorMessage(stateError)} Open Diagnostics to check the install.
        </InfoNote>
      ) : null}

      {needsLink && (
        <div className="setup-callout">
          <span className="large-icon">
            <Smartphone size={24} />
          </span>
          <div>
            <h2>
              {state?.unlinked
                ? "Signal removed this computer"
                : "Link your Signal account"}
            </h2>
            <p>
              {state?.unlinked
                ? "It was removed from Linked devices on your phone. Link it again to keep transcribing."
                : "Scan a QR code with your phone, like setting up Signal Desktop. It takes a minute."}
            </p>
          </div>
          <Button onClick={() => setLinking(true)}>
            <Link2 size={16} />
            {state?.unlinked ? "Link again" : "Link Signal"}
          </Button>
        </div>
      )}

      {!needsLink && beat?.state === "needs_attention" && (
        <InfoNote warning>
          {beat.detail}{" "}
          <button
            className="text-action"
            onClick={() => navigate("Diagnostics")}
          >
            Open Diagnostics
          </button>
        </InfoNote>
      )}
      {model?.fallback && <InfoNote>{model.fallback}.</InfoNote>}

      <section
        className="route-panel"
        aria-label="How your voice notes are handled"
      >
        <div className="route-panel-heading">
          <div>
            <h2>From voice note to something you can read</h2>
            <p>
              The audio is transcribed here. Only the text is sent back, through
              Signal, {inChat ? "into the same chat" : "to your Note to Self"}.
            </p>
          </div>
          <ShieldCheck size={22} />
        </div>
        <div className="message-route">
          <div className="voice-note">
            <span className="voice-note-icon">
              <AudioLines size={23} />
            </span>
            <div className="waveform" aria-hidden="true">
              {[
                10, 18, 12, 26, 38, 20, 30, 44, 26, 14, 34, 24, 40, 18, 30, 10,
                24, 36, 20, 14,
              ].map((height, i) => (
                <i key={i} style={{ height }} />
              ))}
            </div>
            <span>Voice note</span>
          </div>
          <div className="route-connector" aria-hidden="true">
            <span />
            <ChevronRight size={18} />
          </div>
          <div className="route-engine">
            <Cpu size={22} />
            <strong>
              Whisper{" "}
              {model?.model ||
                (config.transcription.model === "auto"
                  ? ""
                  : config.transcription.model)}
            </strong>
            <span className="pill local">
              {model
                ? `This computer · ${model.device.toUpperCase()}`
                : "This computer"}
            </span>
          </div>
          <div className="route-connector" aria-hidden="true">
            <span />
            <ChevronRight size={18} />
          </div>
          <div className="readable-note">
            <FileText size={21} />
            <div>
              <strong>Text in Signal</strong>
              <small>
                {inChat
                  ? "Replies to the voice note"
                  : "Private, in Note to Self"}
              </small>
            </div>
          </div>
        </div>
        <button className="text-action" onClick={() => navigate("Delivery")}>
          Change where transcripts go <ChevronRight size={14} />
        </button>
      </section>

      <div className="summary-strip three">
        <div className="summary-card">
          <span className="summary-icon">
            <RadioTower size={18} />
          </span>
          <div>
            <small>Signal</small>
            <strong>
              {needsLink
                ? "Not linked"
                : !running
                  ? "Paused"
                  : beat?.signal?.connected
                    ? `Connected · ${since(beat.signal.since)}`
                    : "Connecting…"}
            </strong>
            {state?.account && !needsLink && <span>{state.account}</span>}
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon">
            <Cpu size={18} />
          </span>
          <div>
            <small>Speech model</small>
            <strong>
              {model
                ? `${model.model} · ${model.ready ? "ready" : model.loading ? "loading…" : "loads on first note"}`
                : config.transcription.model === "auto"
                  ? "Chosen automatically"
                  : config.transcription.model}
            </strong>
            <span>
              {model
                ? `${model.device.toUpperCase()} · ${model.compute_type}`
                : "Starts with the engine"}
            </span>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon">
            <AudioLines size={18} />
          </span>
          <div>
            <small>Today</small>
            <strong>
              {today.done || 0} transcribed
              {today.failed ? ` · ${today.failed} failed` : ""}
            </strong>
            <span>
              {pending
                ? `${pending} waiting`
                : beat?.last
                  ? `Last one ${since(beat.last.at)} ago (${Math.round(beat.last.seconds)} s)`
                  : "Nothing waiting"}
            </span>
          </div>
        </div>
      </div>

      <div className="overview-columns">
        <section>
          <div className="section-heading inline-heading">
            <h2>Recent transcripts</h2>
            <button className="text-action" onClick={() => navigate("History")}>
              History <ChevronRight size={14} />
            </button>
          </div>
          <div className="recent-list">
            {hours === 0 ? (
              <div className="empty-state">
                <FileText size={28} />
                <h3>History is off</h3>
                <p>
                  Transcripts only go to Signal. Keep a searchable copy on this
                  computer for as long as you choose.
                </p>
                <Button variant="outline" onClick={() => navigate("History")}>
                  Turn on history
                </Button>
              </div>
            ) : recent.isError ? (
              <InfoNote warning>{errorMessage(recent.error)}</InfoNote>
            ) : recent.isPending ? (
              <p className="subtle">Loading…</p>
            ) : recent.data?.length ? (
              recent.data.map((item) => (
                <button
                  key={item.id}
                  className="recent-item"
                  onClick={() => navigate("History")}
                >
                  <span className="contact-avatar">
                    {item.conversation.charAt(0).toUpperCase()}
                  </span>
                  <div>
                    <div className="recent-meta">
                      <strong>{item.conversation || "Signal chat"}</strong>
                      <time>
                        {new Date(item.created_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </time>
                    </div>
                    <p>{item.transcript}</p>
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
                  </div>
                </button>
              ))
            ) : (
              <div className="empty-state">
                <FileText size={28} />
                <h3>No transcripts yet</h3>
                <p>
                  New voice notes appear here. Kept for{" "}
                  {retentionLabel(hours).toLowerCase()}.
                </p>
              </div>
            )}
          </div>
        </section>
        <section>
          <div className="section-heading">
            <h2>Private by design</h2>
            <p>What happens to your messages.</p>
          </div>
          <ul className="privacy-list">
            <li>
              <ShieldCheck size={17} />
              <span>
                <strong>Audio never leaves this computer.</strong> Whisper runs
                here; there's no cloud transcription and no account to create.
              </span>
            </li>
            <li>
              <LockKeyhole size={17} />
              <span>
                <strong>
                  {inChat
                    ? "Transcripts reply in the chat."
                    : "Only you see transcripts."}
                </strong>{" "}
                {inChat
                  ? "Everyone in that chat can read them."
                  : "They arrive in your Note to Self, synced to your devices by Signal."}
              </span>
            </li>
            <li>
              <FileText size={17} />
              <span>
                <strong>Nothing piles up.</strong> Photos and files are deleted
                as they arrive; voice notes once transcribed.{" "}
                {hours === 0
                  ? "No history is kept."
                  : `History is kept for ${retentionLabel(hours).toLowerCase()}.`}
              </span>
            </li>
          </ul>
        </section>
      </div>
      <LinkDialog open={linking} onOpenChange={setLinking} />
    </div>
  );
}

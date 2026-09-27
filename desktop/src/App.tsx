import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AudioLines,
  Check,
  ChevronRight,
  LoaderCircle,
  Monitor,
  Moon,
  Pause,
  Play,
  Search,
  Sun,
} from "lucide-react";
import { Button } from "./components/ui/button";
import { Dialog } from "./components/ui/dialog";
import { WorkspaceProvider, useWorkspace } from "./lib/workspace";
import { api, errorMessage, isDemo } from "./lib/tauri";
import { applyTheme } from "./lib/theme";
import { navigation, navigationGroups } from "./lib/navigation";
import { Overview } from "./pages/overview";
import { HistoryPage } from "./pages/history";
import { DiagnosticsPage } from "./pages/diagnostics";
import { SettingsPages } from "./pages/settings-pages";
import { InfoNote } from "./components/settings";
import type { AppState, Page, Theme } from "./lib/types";

const isMac =
  typeof navigator !== "undefined" &&
  /Mac|iPhone|iPad/.test(navigator.platform);

export function engineSummary(
  state: AppState | undefined,
  failed: boolean,
): { label: string; tone: "online" | "busy" | "warning" | "off" } {
  if (failed) return { label: "Not connected", tone: "warning" };
  if (!state) return { label: "Connecting…", tone: "off" };
  if (!state.linked || state.unlinked)
    return { label: "Not linked", tone: "warning" };
  const beat = state.heartbeat;
  if (beat?.state === "needs_attention" && !beat.stale)
    return { label: "Needs attention", tone: "warning" };
  if (state.engine.status === "backoff")
    return { label: "Restarting…", tone: "busy" };
  if (!state.engine.running) return { label: "Paused", tone: "off" };
  if (!beat || beat.stale || beat.state === "starting")
    return { label: "Starting…", tone: "busy" };
  if (beat.state === "reconnecting")
    return { label: "Reconnecting…", tone: "busy" };
  if (beat.active) return { label: "Transcribing…", tone: "online" };
  return { label: "Listening", tone: "online" };
}

export default function App() {
  return (
    <WorkspaceProvider>
      <AppShell />
    </WorkspaceProvider>
  );
}
function AppShell() {
  const {
    config,
    dirty,
    saving,
    save,
    discard,
    notice,
    update,
    applyError,
    clearApplyError,
  } = useWorkspace();
  const initial = new URLSearchParams(location.search).get("page");
  const [page, setPage] = useState<Page>(
    navigation.find((p) => p.name === initial)?.name || "Overview",
  );
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [page]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [action, setAction] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const state = useQuery({
    queryKey: ["state"],
    queryFn: api.state,
    refetchInterval: 3000,
    retry: false,
  });
  const previewTheme = isDemo
    ? new URLSearchParams(location.search).get("theme")
    : null;
  const theme: Theme =
    previewTheme === "light" || previewTheme === "dark"
      ? previewTheme
      : config.desktop?.theme || "system";
  useEffect(() => applyTheme(theme), [theme]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const armed = !!state.data && state.data.engine.status !== "stopped";
  const canStart = !!state.data && state.data.linked && !state.data.unlinked;
  async function engine(command: "start" | "stop") {
    setAction(command);
    try {
      await api.engine(command);
      clearApplyError?.();
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      notice(
        command === "stop"
          ? "Paused. Voice notes that arrive now are transcribed when you start again."
          : "Starting. Voice notes will be transcribed as they arrive.",
      );
    } catch (error) {
      notice(errorMessage(error), true);
    } finally {
      setAction(null);
    }
  }
  const summary = engineSummary(state.data, state.isError);
  const matches = navigation.filter((n) =>
    `${n.name} ${n.hint}`.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => setPage("Overview")}
          aria-label="Signal Scribe overview"
        >
          <span className="brand-symbol">
            <AudioLines size={22} />
          </span>
          <span>
            <strong>Signal Scribe</strong>
            <small>Voice notes, as text.</small>
          </span>
        </button>
        <button
          className="sidebar-search"
          onClick={() => {
            setSearch("");
            setSearchOpen(true);
          }}
        >
          <Search size={16} />
          <span>Find a setting</span>
          <kbd>{isMac ? "⌘ K" : "Ctrl K"}</kbd>
        </button>
        <nav aria-label="Main navigation">
          {navigationGroups.map((group) => (
            <div className="nav-group" key={group}>
              <p>{group}</p>
              {navigation
                .filter((n) => n.group === group)
                .map(({ name, icon: Icon }) => (
                  <button
                    key={name}
                    title={name}
                    aria-label={name}
                    className={`nav-item ${page === name ? "active" : ""}`}
                    aria-current={page === name ? "page" : undefined}
                    onClick={() => setPage(name)}
                  >
                    <Icon size={18} />
                    <span>{name}</span>
                  </button>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="device-label">
            <span className={`status-dot ${summary.tone}`} />
            <span>{summary.label}</span>
          </div>
          <div className="theme-picker" aria-label="Appearance">
            {(
              [
                ["system", Monitor],
                ["light", Sun],
                ["dark", Moon],
              ] as const
            ).map(([value, Icon]) => (
              <button
                key={value}
                title={`${value[0].toUpperCase() + value.slice(1)} theme`}
                aria-label={`${value} theme`}
                aria-pressed={theme === value}
                className={theme === value ? "selected" : ""}
                onClick={() =>
                  update({ desktop: { ...config.desktop, theme: value } })
                }
              >
                <Icon size={16} />
                <span>{value}</span>
              </button>
            ))}
          </div>
        </div>
      </aside>
      <div className="workspace-main">
        {isDemo && (
          <div className="demo-banner">
            Demo <span>Fictional people and messages. Nothing is sent.</span>
          </div>
        )}
        <header className="app-header">
          <div className="breadcrumb">
            Signal Scribe <ChevronRight size={14} />
            <strong>{page}</strong>
          </div>
          <div className="inline-actions">
            <span
              className={`pill ${summary.tone === "online" ? "local" : "off"}`}
            >
              <span className={`status-dot ${summary.tone}`} />
              {summary.label}
            </span>
            <Button
              variant={armed ? "outline" : "default"}
              disabled={!!action || !state.data || (!armed && !canStart)}
              title={!armed && !canStart ? "Link Signal first" : undefined}
              onClick={() => engine(armed ? "stop" : "start")}
            >
              {action ? (
                <LoaderCircle size={15} className="spin" />
              ) : armed ? (
                <Pause size={14} />
              ) : (
                <Play size={15} />
              )}{" "}
              {armed ? "Pause" : "Start"}
            </Button>
          </div>
        </header>
        <main id="main-content" className="page-container" tabIndex={-1}>
          {applyError && (
            <div className="page-warning">
              <InfoNote warning>{applyError}</InfoNote>
            </div>
          )}
          {page !== "Overview" && (
            <div className="page-heading">
              <div>
                <h1>{page}</h1>
                <p>{navigation.find((n) => n.name === page)?.hint}</p>
              </div>
              {!dirty && (
                <span className="saved-label">
                  <Check size={14} />
                  All changes saved
                </span>
              )}
            </div>
          )}
          {page === "Overview" ? (
            <Overview
              navigate={setPage}
              state={state.data}
              stateError={state.error}
            />
          ) : page === "History" ? (
            <HistoryPage />
          ) : page === "Diagnostics" ? (
            <DiagnosticsPage />
          ) : (
            <SettingsPages page={page} />
          )}
        </main>
        {dirty && (
          <div className="save-bar">
            <div>
              <span className="unsaved-dot" />
              <strong>Unsaved changes</strong>
              <span>Changes apply when you save.</span>
            </div>
            <div className="inline-actions">
              <Button variant="ghost" disabled={saving} onClick={discard}>
                Discard
              </Button>
              <Button onClick={save} disabled={saving}>
                {saving && <LoaderCircle size={15} className="spin" />}
                {saving ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </div>
        )}
      </div>
      <Dialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        title="Find a setting"
        description="Jump to a page."
      >
        <div className="search-input">
          <Search size={18} />
          <input
            autoFocus
            placeholder="Try language, history or start at login…"
            aria-label="Search settings"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="command-results">
          {matches.map(({ name, hint, icon: Icon }) => (
            <button
              key={name}
              onClick={() => {
                setPage(name);
                setSearchOpen(false);
              }}
            >
              <Icon size={19} />
              <span>
                <strong>{name}</strong>
                <small>{hint}</small>
              </span>
              <ChevronRight size={15} />
            </button>
          ))}
          {!matches.length && (
            <p className="subtle">Nothing matches. Try a different word.</p>
          )}
        </div>
      </Dialog>
    </div>
  );
}

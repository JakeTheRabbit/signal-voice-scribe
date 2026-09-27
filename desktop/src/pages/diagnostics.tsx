import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  CircleAlert,
  Copy,
  FolderOpen,
  RotateCw,
  XCircle,
} from "lucide-react";
import { api, errorMessage } from "../lib/tauri";
import { useWorkspace } from "../lib/workspace";
import { Button } from "../components/ui/button";
import { InfoNote } from "../components/settings";

export function DiagnosticsPage() {
  const { notice } = useWorkspace();
  const query = useQuery({
    queryKey: ["diagnostics"],
    queryFn: api.diagnostics,
    retry: false,
  });
  return (
    <div className="stack">
      <div className="inline-actions">
        <Button
          variant="outline"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          <RotateCw size={16} className={query.isFetching ? "spin" : ""} />
          {query.isFetching ? "Checking…" : "Run checks again"}
        </Button>
        <Button
          variant="ghost"
          disabled={!query.data}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(
                query
                  .data!.checks.map(
                    (c) => `${c.name}: ${c.status} - ${c.detail}`,
                  )
                  .join("\n"),
              );
              notice("Copied. It contains no messages or transcripts.");
            } catch {
              notice("The clipboard isn't available.", true);
            }
          }}
        >
          <Copy size={16} />
          Copy results
        </Button>
        <Button
          variant="ghost"
          onClick={() =>
            api.openLogs().catch((error) => notice(errorMessage(error), true))
          }
        >
          <FolderOpen size={16} />
          Open logs folder
        </Button>
      </div>
      {query.isError && (
        <InfoNote warning>{errorMessage(query.error)}</InfoNote>
      )}
      <section className="settings-surface">
        {query.isPending && (
          <p className="subtle diagnostic-loading">Checking this computer…</p>
        )}
        {query.data?.checks.map((check) => (
          <div className="diagnostic-row" key={check.name}>
            {check.status === "ok" ? (
              <CheckCircle2 className="success-text" size={22} />
            ) : check.status === "error" ? (
              <XCircle className="danger-text" size={22} />
            ) : (
              <CircleAlert className="warning-text" size={22} />
            )}
            <div>
              <h2>{check.name}</h2>
              <p>{check.detail}</p>
            </div>
            <span
              className={`pill ${check.status === "ok" ? "local" : "cloud"}`}
            >
              {check.status === "ok"
                ? "OK"
                : check.status === "error"
                  ? "Problem"
                  : "Check"}
            </span>
          </div>
        ))}
      </section>
      <section className="help-section">
        <h2>If a voice note doesn't turn into text</h2>
        <ol>
          <li>
            Make sure the status at the top says Listening. If it says Paused,
            press Start.
          </li>
          <li>
            Look in your Note to Self chat in Signal (or the original chat, if
            you chose that in Delivery).
          </li>
          <li>
            The first voice note after installing can take a minute while the
            speech model loads.
          </li>
          <li>
            Check your phone's Linked devices list. If Signal Scribe is missing,
            link it again from Overview.
          </li>
          <li>
            Still stuck? Open the logs folder and include engine.log when you
            report the problem.
          </li>
        </ol>
      </section>
      <p className="footnote">
        These checks look at this computer only. Signal Scribe's own logs record
        what happened, never message text or transcripts. signal-cli.log comes
        from signal-cli and can mention phone numbers, so read it before sharing
        it.
      </p>
    </div>
  );
}

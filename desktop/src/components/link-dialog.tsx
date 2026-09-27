import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, LoaderCircle, RotateCw } from "lucide-react";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { InfoNote } from "./settings";
import { api, errorMessage } from "../lib/tauri";
import type { LinkStatus } from "../lib/types";

const REASONS: Record<string, string> = {
  expired:
    "The code expired before it was scanned. Get a new one and scan it within a couple of minutes.",
  cancelled: "Linking was cancelled.",
  network:
    "signal-cli couldn't reach Signal. Check your internet connection and try again.",
  already_linked: "This computer is already linked to that account.",
  engine_running: "Signal Scribe is running. Pause it, then link again.",
  runtime_missing:
    "Java or signal-cli is missing. Run the installer again, then retry.",
};

export function LinkDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<LinkStatus>({ state: "idle" });
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  async function begin() {
    setError(null);
    setStatus({ state: "starting" });
    try {
      await api.link();
    } catch (failure) {
      setError(errorMessage(failure));
      setStatus({ state: "failed" });
    }
  }

  useEffect(() => {
    if (!open) {
      started.current = false;
      return;
    }
    if (!started.current) {
      started.current = true;
      void begin();
    }
    const timer = setInterval(async () => {
      try {
        const next = await api.linkStatus();
        setStatus((current) =>
          current.state === "starting" && next.state === "idle"
            ? current
            : next,
        );
        if (next.state === "linked") {
          clearInterval(timer);
          await queryClient.invalidateQueries({ queryKey: ["state"] });
        }
      } catch (failure) {
        setError(errorMessage(failure));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [open]);

  async function close(next: boolean) {
    if (!next && (status.state === "starting" || status.state === "waiting"))
      await api.cancelLink().catch(() => undefined);
    onOpenChange(next);
  }

  async function startEngine() {
    try {
      await api.engine("start");
      await queryClient.invalidateQueries({ queryKey: ["state"] });
      onOpenChange(false);
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => void close(next)}
      title="Link Signal"
      description="Connect this computer the same way you'd connect Signal Desktop."
    >
      {status.state === "linked" ? (
        <div className="link-result">
          <CheckCircle2 size={44} className="success-text" />
          <h3>Linked{status.account ? ` to ${status.account}` : ""}</h3>
          <p>
            Signal Scribe now appears in your phone's Linked devices. Start it
            and your next voice note will arrive as text.
          </p>
          <Button onClick={startEngine}>Start transcribing</Button>
        </div>
      ) : (
        <div className="link-layout">
          <div className="qr-frame" aria-live="polite">
            {status.state === "waiting" && status.qr ? (
              <img src={status.qr} alt="QR code for linking Signal" />
            ) : status.state === "failed" ? (
              <Button variant="outline" onClick={begin}>
                <RotateCw size={16} /> Get a new code
              </Button>
            ) : (
              <span className="subtle">
                <LoaderCircle size={22} className="spin" />
                <br />
                Preparing a link code…
              </span>
            )}
          </div>
          <ol className="link-steps">
            <li>
              Open <strong>Signal</strong> on your phone.
            </li>
            <li>
              Go to <strong>Settings → Linked devices</strong> and tap{" "}
              <strong>Link new device</strong> (the <strong>+</strong> on
              iPhone).
            </li>
            <li>Scan this code. It expires after a few minutes.</li>
          </ol>
        </div>
      )}
      {status.state === "failed" && (
        <InfoNote warning>
          {error ||
            REASONS[status.reason || ""] ||
            "Linking didn't finish. Get a new code to try again."}
        </InfoNote>
      )}
      {status.state !== "failed" && error && (
        <InfoNote warning>{error}</InfoNote>
      )}
      <p className="footnote">
        Linking gives this computer its own keys, stored only in Signal Scribe's
        data folder. Remove it any time from Linked devices on your phone.
      </p>
    </Dialog>
  );
}

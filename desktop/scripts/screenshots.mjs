// Regenerate the README screenshots from the fictional demo workspace.
//
//   pnpm dev            (in one terminal: serves the demo on http://127.0.0.1:1420)
//   pnpm screenshots    (in another; needs Chrome, Chromium or Edge)
//
// Set CHROME=/path/to/chrome if it isn't found automatically.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, "../../docs/images");
const base = process.env.DEMO_URL || "http://127.0.0.1:1420/";
const candidates = [
  process.env.CHROME,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);
const chrome = candidates.find((file) => fs.existsSync(file));
if (!chrome) throw new Error("Chrome not found; set CHROME=/path/to/chrome");

const port = 9333;
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "scribe-shots-"));
const browser = spawn(
  chrome,
  [
    "--headless=new",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "--hide-scrollbars",
    "--force-color-profile=srgb",
    "about:blank",
  ],
  { stdio: "ignore" },
);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let targets = [];
for (let i = 0; i < 50 && !targets.length; i++) {
  try {
    targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  } catch {
    await sleep(200);
  }
}
const ws = new WebSocket(
  targets.find((t) => t.type === "page").webSocketDebuggerUrl,
);
let next = 0;
const pending = new Map();
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
  }
};
await new Promise((resolve) => (ws.onopen = resolve));
const send = (method, params = {}) =>
  new Promise((resolve) => {
    const id = ++next;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
const evaluate = async (expression) =>
  (
    await send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    })
  ).result?.result?.value;
const waitFor = async (expression, timeout = 15000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await evaluate(expression)) return;
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${expression}`);
};
async function capture(
  name,
  url,
  { width = 1440, height = 900, ready, act, after } = {},
) {
  await send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1.5,
    mobile: false,
  });
  await send("Page.navigate", { url });
  await waitFor("document.readyState === 'complete'");
  if (ready) await waitFor(ready);
  if (act) {
    await evaluate(act);
    await waitFor(after);
  }
  await sleep(700);
  const { result } = await send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(
    path.join(out, `${name}.png`),
    Buffer.from(result.data, "base64"),
  );
  console.log("saved", `${name}.png`);
}

await send("Page.enable");
const app =
  "!!document.querySelector('.app-shell') && !document.querySelector('.loading-dot')";
await capture(
  "in-signal",
  pathToFileURL(path.join(out, "in-signal.html")).href,
  {
    width: 1600,
    height: 780,
    ready: "!!document.querySelector('#wave i')",
  },
);
await capture("overview-light", `${base}?demo=1&theme=light`, { ready: app });
await capture("overview-dark", `${base}?demo=1&theme=dark`, { ready: app });
await capture(
  "link-light",
  `${base}?demo=1&theme=light&state=unlinked&dialog=link`,
  {
    ready: "!!document.querySelector('.qr-frame img')",
  },
);
await capture("history-dark", `${base}?demo=1&theme=dark&page=History`, {
  ready: "document.querySelectorAll('.history-item').length > 3",
  act: "document.querySelector('.history-item').click()",
  after: "!!document.querySelector('.history-detail blockquote')",
});
await capture(
  "transcription-light",
  `${base}?demo=1&theme=light&page=Transcription`,
  { ready: app },
);
await capture("delivery-dark", `${base}?demo=1&theme=dark&page=Delivery`, {
  ready: app,
});
await capture(
  "diagnostics-light",
  `${base}?demo=1&theme=light&page=Diagnostics`,
  {
    ready: "document.querySelectorAll('.diagnostic-row').length > 5",
  },
);
ws.close();
browser.kill();

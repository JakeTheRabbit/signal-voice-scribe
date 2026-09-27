import {
  Activity,
  AudioLines,
  History,
  LayoutDashboard,
  MonitorCog,
  Send,
} from "lucide-react";
import type { Page } from "./types";

export const navigation = [
  {
    name: "Overview",
    icon: LayoutDashboard,
    group: "Signal Scribe",
    hint: "Status, linking and recent transcripts",
  },
  {
    name: "History",
    icon: History,
    group: "Signal Scribe",
    hint: "Search, replay and auto-delete transcripts",
  },
  {
    name: "Transcription",
    icon: AudioLines,
    group: "Settings",
    hint: "Speech model, language and which notes to transcribe",
  },
  {
    name: "Delivery",
    icon: Send,
    group: "Settings",
    hint: "Where transcripts appear in Signal",
  },
  {
    name: "App",
    icon: MonitorCog,
    group: "Settings",
    hint: "Appearance, start at login and startup",
  },
  {
    name: "Diagnostics",
    icon: Activity,
    group: "Help",
    hint: "Checks, logs and troubleshooting",
  },
] satisfies {
  name: Page;
  icon: typeof Activity;
  group: string;
  hint: string;
}[];

export const navigationGroups = ["Signal Scribe", "Settings", "Help"];

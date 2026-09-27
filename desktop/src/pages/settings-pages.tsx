import type { Page } from "../lib/types";
import { AppPage } from "./settings/app";
import { DeliveryPage } from "./settings/delivery";
import { TranscriptionPage } from "./settings/transcription";

export function SettingsPages({ page }: { page: Page }) {
  switch (page) {
    case "Transcription":
      return <TranscriptionPage />;
    case "Delivery":
      return <DeliveryPage />;
    case "App":
      return <AppPage />;
    default:
      return null;
  }
}

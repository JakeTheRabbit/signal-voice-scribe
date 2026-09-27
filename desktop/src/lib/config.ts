import type { AppConfig } from "./types";

const DEFAULTS: Pick<
  AppConfig,
  "transcription" | "delivery" | "history" | "desktop"
> = {
  transcription: {
    model: "auto",
    device: "auto",
    compute_type: "auto",
    language: null,
    incoming: true,
    outgoing: true,
    groups: true,
    audio_files: false,
    max_minutes: 60,
  },
  delivery: { mode: "note_to_self", notify: true, failure_notices: true },
  history: {
    retention_hours: 0,
    conversation_retention_hours: {},
    keep_audio: true,
  },
  desktop: { theme: "system", start_engine_on_launch: true },
};

/** Fill in any section the backend omitted, so pages can read settings directly. */
export function normalizeConfig(config: Partial<AppConfig>): AppConfig {
  if (!config || typeof config !== "object" || Array.isArray(config))
    throw new Error("Settings are unreadable. Fix or delete config.json.");
  const merged: AppConfig = {
    ...structuredClone(DEFAULTS),
    ...config,
  } as AppConfig;
  for (const section of [
    "transcription",
    "delivery",
    "history",
    "desktop",
  ] as const)
    merged[section] = {
      ...DEFAULTS[section],
      ...((config[section] ?? {}) as object),
    } as never;
  merged.schema_version = config.schema_version ?? 3;
  return merged;
}

/** Top-level sections that differ; the backend merges them into the saved file. */
export function configPatch(
  original: AppConfig,
  draft: AppConfig,
): Partial<AppConfig> {
  return Object.fromEntries(
    Object.entries(draft).filter(
      ([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key]),
    ),
  );
}

export const MODELS: { value: string; label: string; detail: string }[] = [
  { value: "auto", label: "Automatic", detail: "Best fit for this computer" },
  { value: "tiny", label: "Tiny", detail: "~75 MB · fastest, least accurate" },
  { value: "base", label: "Base", detail: "~145 MB · fast" },
  {
    value: "small",
    label: "Small",
    detail: "~480 MB · good on most computers",
  },
  { value: "medium", label: "Medium", detail: "~1.5 GB · accurate, slower" },
  {
    value: "large-v3-turbo",
    label: "Large v3 Turbo",
    detail: "~1.6 GB · best with an NVIDIA GPU",
  },
  { value: "large-v3", label: "Large v3", detail: "~3 GB · most accurate" },
  {
    value: "distil-large-v3",
    label: "Distil Large v3",
    detail: "~1.5 GB · English, fast",
  },
  { value: "tiny.en", label: "Tiny (English)", detail: "~75 MB" },
  { value: "base.en", label: "Base (English)", detail: "~145 MB" },
  { value: "small.en", label: "Small (English)", detail: "~480 MB" },
  { value: "medium.en", label: "Medium (English)", detail: "~1.5 GB" },
];

// Every language Whisper recognises (100), so anyone can pin theirs.
const WHISPER_LANGUAGES =
  "af:Afrikaans,am:Amharic,ar:Arabic,as:Assamese,az:Azerbaijani,ba:Bashkir,be:Belarusian,bg:Bulgarian,bn:Bengali,bo:Tibetan,br:Breton,bs:Bosnian,ca:Catalan,cs:Czech,cy:Welsh,da:Danish,de:German,el:Greek,en:English,es:Spanish,et:Estonian,eu:Basque,fa:Persian,fi:Finnish,fo:Faroese,fr:French,gl:Galician,gu:Gujarati,ha:Hausa,haw:Hawaiian,he:Hebrew,hi:Hindi,hr:Croatian,ht:Haitian Creole,hu:Hungarian,hy:Armenian,id:Indonesian,is:Icelandic,it:Italian,ja:Japanese,jw:Javanese,ka:Georgian,kk:Kazakh,km:Khmer,kn:Kannada,ko:Korean,la:Latin,lb:Luxembourgish,ln:Lingala,lo:Lao,lt:Lithuanian,lv:Latvian,mg:Malagasy,mi:Māori,mk:Macedonian,ml:Malayalam,mn:Mongolian,mr:Marathi,ms:Malay,mt:Maltese,my:Burmese,ne:Nepali,nl:Dutch,nn:Norwegian Nynorsk,no:Norwegian,oc:Occitan,pa:Punjabi,pl:Polish,ps:Pashto,pt:Portuguese,ro:Romanian,ru:Russian,sa:Sanskrit,sd:Sindhi,si:Sinhala,sk:Slovak,sl:Slovenian,sn:Shona,so:Somali,sq:Albanian,sr:Serbian,su:Sundanese,sv:Swedish,sw:Swahili,ta:Tamil,te:Telugu,tg:Tajik,th:Thai,tk:Turkmen,tl:Tagalog,tr:Turkish,tt:Tatar,uk:Ukrainian,ur:Urdu,uz:Uzbek,vi:Vietnamese,yi:Yiddish,yo:Yoruba,yue:Cantonese,zh:Chinese";

export const LANGUAGES: [string, string][] = [
  ["", "Detect automatically"],
  ...WHISPER_LANGUAGES.split(",")
    .map((pair) => pair.split(":") as [string, string])
    .sort((a, b) => a[1].localeCompare(b[1])),
];

export function retentionLabel(hours: number): string {
  if (hours === 0) return "Not kept";
  if (hours < 0) return "Until you delete it";
  if (hours % 24 === 0) {
    const days = hours / 24;
    return `${days} day${days === 1 ? "" : "s"}`;
  }
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

export function durationLabel(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return "";
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

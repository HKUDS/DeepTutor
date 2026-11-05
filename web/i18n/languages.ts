/** UI locales that have a selectable bundle. The bundles may fall back to English per key. */
export const APP_LANGUAGES = [
  { code: "en", labelKey: "language.english" },
  { code: "zh", labelKey: "language.chinese" },
  { code: "fr", labelKey: "language.french" },
  { code: "de", labelKey: "language.german" },
  { code: "uk", labelKey: "language.ukrainian" },
  { code: "pl", labelKey: "language.polish" },
  { code: "pt", labelKey: "language.portuguese" },
  { code: "vi", labelKey: "language.vietnamese" },
  { code: "ja", labelKey: "language.japanese" },
  { code: "tr", labelKey: "language.turkish" },
] as const;

export type AppLanguage = (typeof APP_LANGUAGES)[number]["code"];

const SUPPORTED_CODES: ReadonlySet<string> = new Set(
  APP_LANGUAGES.map(({ code }) => code),
);

export function isAppLanguage(value: unknown): value is AppLanguage {
  return typeof value === "string" && SUPPORTED_CODES.has(value);
}

export function normalizeLanguage(value: unknown): AppLanguage {
  if (typeof value !== "string") return "en";
  const code = value.trim().toLowerCase().replaceAll("_", "-");
  const base = code.split("-", 1)[0];
  if (base === "zh" || base === "cn" || code === "chinese") return "zh";
  if (base === "fr" || code === "french") return "fr";
  if (base === "de" || code === "german" || code === "deutsch") return "de";
  if (base === "uk" || base === "ua" || code === "ukrainian") return "uk";
  if (base === "pl" || code === "polish" || code === "polski") return "pl";
  if (base === "pt" || code === "portuguese" || code === "português") return "pt";
  if (base === "vi" || code === "vietnamese" || code === "tiếng việt") return "vi";
  if (base === "ja" || base === "jp" || code === "japanese") return "ja";
  if (base === "tr" || code === "turkish" || code === "türkçe") return "tr";
  return "en";
}

/** Model output can use more languages than the app UI locale supports. */
export type ResponseLanguage =
  | "en"
  | "zh"
  | "zh-tw"
  | "ja"
  | "ko"
  | "es"
  | "fr"
  | "de"
  | "ru"
  | "pt"
  | "it"
  | "ar"
  | "pl"
  | "uk"
  | "ms"
  | "vi"
  | "tr";

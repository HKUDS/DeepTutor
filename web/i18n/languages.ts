/** UI locales that have a selectable bundle. The bundles may fall back to English per key. */
export const APP_LANGUAGES = [
  { code: "en", labelKey: "language.english" },
  { code: "zh", labelKey: "language.chinese" },
  { code: "fr", labelKey: "language.french" },
  { code: "uk", labelKey: "language.ukrainian" },
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
  if (base === "uk" || base === "ua" || code === "ukrainian") return "uk";
  return "en";
}

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
  { code: "ko", labelKey: "language.korean" },
  { code: "it", labelKey: "language.italian" },
  { code: "hu", labelKey: "language.hungarian" },
  { code: "fa", labelKey: "language.persian" },
] as const;

export type AppLanguage = (typeof APP_LANGUAGES)[number]["code"];

const SUPPORTED_CODES: ReadonlySet<string> = new Set(
  APP_LANGUAGES.map(({ code }) => code),
);

export function isAppLanguage(value: unknown): value is AppLanguage {
  return typeof value === "string" && SUPPORTED_CODES.has(value);
}

/**
 * Text direction per locale. Declared explicitly rather than inferred from a
 * script or a language list: `DECISIONS.md` D-02 requires the direction to be
 * a stated property of the locale, so a future right-to-left locale cannot
 * silently inherit `ltr` just because nobody remembered to add it here.
 */
export const RTL_LANGUAGES: ReadonlySet<AppLanguage> = new Set<AppLanguage>(["fa"]);

export type TextDirection = "ltr" | "rtl";

export function textDirection(language: AppLanguage): TextDirection {
  return RTL_LANGUAGES.has(language) ? "rtl" : "ltr";
}

/**
 * The BCP-47 tag used for `Intl` formatting and the document `lang` attribute.
 *
 * The interface locale is the short key (`fa`); the *regional* tag is what
 * dates, numbers and collation need. Persian in Iran is `fa-IR`: calendar
 * defaults, digit shapes and the date order all follow from the region, not
 * from the bare language subtag. Kept as a lookup rather than a template so a
 * locale whose formatting region is not simply its own code can be added
 * without a special case at every call site.
 */
const REGIONAL_LOCALE_TAGS: Partial<Record<AppLanguage, string>> = {
  fa: "fa-IR",
  zh: "zh-CN",
};

export function regionalLocale(language: AppLanguage): string {
  return REGIONAL_LOCALE_TAGS[language] ?? language;
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
  if (base === "ko" || code === "korean" || code === "한국어") return "ko";
  if (base === "it" || code === "italian" || code === "italiano") return "it";
  if (base === "hu" || code === "hungarian" || code === "magyar") return "hu";
  if (base === "fa" || code === "persian" || code === "farsi" || code === "فارسی")
    return "fa";
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
  | "tr"
  | "hi"
  | "hu"
  | "fa";

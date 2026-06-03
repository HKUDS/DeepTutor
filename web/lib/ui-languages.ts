export const SUPPORTED_UI_LANGUAGES = ["en", "zh", "de"] as const;

export type AppLanguage = (typeof SUPPORTED_UI_LANGUAGES)[number];

export const uiLanguageOptions: Array<{
  value: AppLanguage;
  labelKey: "language.english" | "language.chinese" | "language.german";
}> = [
  { value: "en", labelKey: "language.english" },
  { value: "zh", labelKey: "language.chinese" },
  { value: "de", labelKey: "language.german" },
];

export function isSupportedUiLanguage(
  value: unknown,
): value is AppLanguage {
  return SUPPORTED_UI_LANGUAGES.includes(value as AppLanguage);
}

export function normalizeUiLanguage(
  value: unknown,
): AppLanguage {
  if (value == null) return "en";

  const language = String(value).trim().toLowerCase();
  if (language === "en" || language === "english" || language.startsWith("en-")) {
    return "en";
  }
  if (language === "zh" || language === "cn" || language === "chinese") {
    return "zh";
  }
  if (
    language === "de" ||
    language === "german" ||
    language === "deutsch" ||
    language.startsWith("de-") ||
    language.startsWith("de_")
  ) {
    return "de";
  }

  return "en";
}

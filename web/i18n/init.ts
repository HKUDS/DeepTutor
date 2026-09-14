import i18n, { type Resource } from "i18next";
import { initReactI18next } from "react-i18next";

import enApp from "@/locales/en/app.json";

export type AppLanguage = "en" | "zh" | "uk";

/**
 * The languages the app offers, in menu order — the single source of truth for
 * every language picker. Pickers used to hardcode `["en", "zh"]` inline, so a
 * new locale had to be added in each of them and was silently missing from the
 * ones nobody remembered.
 */
export const APP_LANGUAGES: readonly { code: AppLanguage; labelKey: string }[] = [
  { code: "en", labelKey: "language.english" },
  { code: "zh", labelKey: "language.chinese" },
  { code: "uk", labelKey: "language.ukrainian" },
];

export function normalizeLanguage(lang: unknown): AppLanguage {
  if (!lang) return "en";
  const s = String(lang).toLowerCase();
  if (s === "zh" || s === "cn" || s === "chinese") return "zh";
  if (s === "uk" || s === "ua" || s === "ukrainian") return "uk";
  return "en";
}

let _initialized = false;

export function initI18n(language?: unknown) {
  if (_initialized) return i18n;

  const resources: Resource = {
    en: { app: enApp },
  };

  i18n.use(initReactI18next).init({
    resources,
    lng: normalizeLanguage(language),
    fallbackLng: "en",
    // Use a single default namespace to keep lookups simple.
    // We intentionally keep keySeparator disabled so keys like "Generating..." remain valid.
    defaultNS: "app",
    ns: ["app"],
    keySeparator: false,
    interpolation: {
      escapeValue: false,
    },
    returnEmptyString: false,
    returnNull: false,
  });

  _initialized = true;
  return i18n;
}

export async function ensureLanguage(language: AppLanguage) {
  if (i18n.hasResourceBundle(language, "app")) return;
  if (language === "zh") {
    const zhApp = (await import("@/locales/zh/app.json")).default;
    i18n.addResourceBundle("zh", "app", zhApp, true, true);
  }
  if (language === "uk") {
    const ukApp = (await import("@/locales/uk/app.json")).default;
    i18n.addResourceBundle("uk", "app", ukApp, true, true);
  }
}

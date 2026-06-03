import i18n, { type Resource } from "i18next";
import { initReactI18next } from "react-i18next";

import enApp from "@/locales/en/app.json";
import {
  normalizeUiLanguage,
  type AppLanguage,
} from "../lib/ui-languages";

export type { AppLanguage } from "../lib/ui-languages";

export function normalizeLanguage(lang: unknown): AppLanguage {
  return normalizeUiLanguage(lang);
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
  if (language === "de") {
    const deApp = (await import("@/locales/de/app.json" as string)).default;
    i18n.addResourceBundle("de", "app", deApp, true, true);
  }
}

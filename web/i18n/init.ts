import i18n, {
  createInstance,
  type i18n as I18nInstance,
  type Resource,
} from "i18next";
import { initReactI18next } from "react-i18next";

import enApp from "@/locales/en/app.json";
import zhApp from "@/locales/zh/app.json";

export type AppLanguage = "en" | "zh";

export function normalizeLanguage(lang: unknown): AppLanguage {
  if (!lang) return "en";
  const s = String(lang).toLowerCase();
  if (s === "zh" || s === "cn" || s === "chinese") return "zh";
  return "en";
}

let _initialized = false;

const resources: Resource = {
  en: { app: enApp },
  zh: { app: zhApp },
};

function initializeInstance(
  instance: I18nInstance,
  language?: unknown,
): I18nInstance {
  void instance.use(initReactI18next).init({
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
    initImmediate: false,
  });

  return instance;
}

export function createI18nInstance(language?: unknown): I18nInstance {
  return initializeInstance(createInstance(), language);
}

export function initI18n(language?: unknown) {
  if (_initialized) return i18n;

  initializeInstance(i18n, language);
  _initialized = true;
  return i18n;
}

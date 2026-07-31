"use client";

import { useEffect, useState } from "react";
import { I18nextProvider } from "react-i18next";

import {
  createI18nInstance,
  initI18n,
  normalizeLanguage,
  type AppLanguage,
} from "./init";

// Initialize i18next at module load (before any React render) so that the
// `init()` call — which fires `initialized` / `languageChanged` events that
// trigger setState on subscribed components — never happens during another
// component's render phase. Calling `initI18n` from the render body would
// produce the React warning:
//   "Cannot update a component (`X`) while rendering a different component
//   (`I18nProvider`)."
const globalI18n = initI18n();

export function I18nProvider({
  language,
  children,
}: {
  language: AppLanguage | string;
  children: React.ReactNode;
}) {
  const [instance] = useState(() => createI18nInstance(language));

  useEffect(() => {
    const nextLang = normalizeLanguage(language);
    if (instance.language !== nextLang) {
      void instance.changeLanguage(nextLang);
    }
    if (globalI18n.language !== nextLang) {
      void globalI18n.changeLanguage(nextLang);
    }
    // Keep <html lang="..."> in sync for accessibility & Intl defaults.
    document.documentElement.lang = nextLang;
  }, [instance, language]);

  return <I18nextProvider i18n={instance}>{children}</I18nextProvider>;
}

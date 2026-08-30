"use client";

import { useEffect, useState } from "react";
import i18n from "i18next";

import {
  ensureLanguage,
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
initI18n();

export function I18nProvider({
  language,
  enabled = true,
  children,
}: {
  language: AppLanguage | string;
  enabled?: boolean;
  children: React.ReactNode;
}) {
  const nextLang = normalizeLanguage(language);
  const [readyLanguage, setReadyLanguage] = useState<AppLanguage | null>(() =>
    enabled &&
    i18n.language === nextLang &&
    i18n.hasResourceBundle(nextLang, "app")
      ? nextLang
      : null,
  );

  useEffect(() => {
    let cancelled = false;
    if (!enabled) return () => undefined;
    void ensureLanguage(nextLang).then(async () => {
      if (cancelled) return;
      if (i18n.language !== nextLang) {
        await i18n.changeLanguage(nextLang);
      }
      if (cancelled) return;
      // Keep <html lang="..."> in sync for accessibility & Intl defaults.
      document.documentElement.lang = nextLang;
      setReadyLanguage(nextLang);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, nextLang]);

  if (!enabled || readyLanguage !== nextLang) {
    return (
      <div
        aria-busy="true"
        aria-hidden="true"
        className="min-h-dvh bg-[var(--background)]"
      />
    );
  }
  return children;
}

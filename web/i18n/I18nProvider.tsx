"use client";

import { useEffect, useState } from "react";
import i18n from "i18next";

import {
  ensureLanguage,
  initI18n,
  normalizeLanguage,
  regionalLocale,
  textDirection,
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
      // Keep <html lang="..."> in sync for accessibility, `Intl` defaults and
      // the `:lang()` font stacks in globals.css. The document carries the
      // *regional* tag (`fa-IR`, not `fa`): CSS `:lang(fa)` still matches a
      // `fa-IR` element by prefix, while `Intl`/screen readers get the region
      // they need to pick the Iranian calendar and digit shapes.
      const root = document.documentElement;
      root.lang = regionalLocale(nextLang);
      // Direction is set from the locale's declared property, never guessed
      // from the script (D-02). Until step 1.3 lands the logical-property
      // conversion, `rtl` is intentionally inert: the shell is still laid out
      // with physical properties. The attribute is correct from day one so
      // the RTL work has a single source of truth to build on.
      root.dir = textDirection(nextLang);
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

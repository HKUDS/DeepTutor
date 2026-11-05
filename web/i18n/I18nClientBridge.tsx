"use client";

import { useEffect } from "react";

import { useAppShell } from "@/context/AppShellContext";
import { I18nProvider } from "./I18nProvider";

export function I18nClientBridge({ children }: { children: React.ReactNode }) {
  const { language, languageReady } = useAppShell();

  // Keep <html lang/dir> in step with the active locale so Persian renders
  // right-to-left (and switching back to an LTR locale restores the flow)
  // without a reload.
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.lang = language;
    document.documentElement.dir = language === "fa" ? "rtl" : "ltr";
  }, [language]);

  return (
    <I18nProvider language={language} enabled={languageReady}>
      {children}
    </I18nProvider>
  );
}

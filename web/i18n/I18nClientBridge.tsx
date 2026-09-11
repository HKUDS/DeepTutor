"use client";

import { useAppShell } from "@/context/AppShellContext";
import { I18nProvider } from "./I18nProvider";

export function I18nClientBridge({ children }: { children: React.ReactNode }) {
  const { language, languageReady } = useAppShell();

  return (
    <I18nProvider language={language} enabled={languageReady}>
      {children}
    </I18nProvider>
  );
}

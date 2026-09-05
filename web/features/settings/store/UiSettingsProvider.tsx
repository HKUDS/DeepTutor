"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useSettings, type SettingsContextValue } from "./SettingsStore";

type UiSettingsSlice = Pick<
  SettingsContextValue,
  | "theme"
  | "language"
  | "responseLanguage"
  | "codeBlockTheme"
  | "codeBlockShowLineNumbers"
  | "codeBlockWrapLongLines"
  | "experimentalMasteryPlanning"
  | "updateTheme"
  | "updateLanguage"
  | "updateResponseLanguage"
  | "updateCodeBlockTheme"
  | "updateCodeBlockShowLineNumbers"
  | "updateCodeBlockWrapLongLines"
  | "updateExperimentalMasteryPlanning"
>;

const UiSettingsContext = createContext<UiSettingsSlice | null>(null);

export function UiSettingsProvider({ children }: { children: ReactNode }) {
  const source = useSettings();
  const value = useMemo<UiSettingsSlice>(
    () => ({
      theme: source.theme,
      language: source.language,
      responseLanguage: source.responseLanguage,
      codeBlockTheme: source.codeBlockTheme,
      codeBlockShowLineNumbers: source.codeBlockShowLineNumbers,
      codeBlockWrapLongLines: source.codeBlockWrapLongLines,
      experimentalMasteryPlanning: source.experimentalMasteryPlanning,
      updateTheme: source.updateTheme,
      updateLanguage: source.updateLanguage,
      updateResponseLanguage: source.updateResponseLanguage,
      updateCodeBlockTheme: source.updateCodeBlockTheme,
      updateCodeBlockShowLineNumbers: source.updateCodeBlockShowLineNumbers,
      updateCodeBlockWrapLongLines: source.updateCodeBlockWrapLongLines,
      updateExperimentalMasteryPlanning: source.updateExperimentalMasteryPlanning,
    }),
    [
      source.theme,
      source.language,
      source.responseLanguage,
      source.codeBlockTheme,
      source.codeBlockShowLineNumbers,
      source.codeBlockWrapLongLines,
      source.experimentalMasteryPlanning,
      source.updateTheme,
      source.updateLanguage,
      source.updateResponseLanguage,
      source.updateCodeBlockTheme,
      source.updateCodeBlockShowLineNumbers,
      source.updateCodeBlockWrapLongLines,
      source.updateExperimentalMasteryPlanning,
    ],
  );
  return (
    <UiSettingsContext.Provider value={value}>
      {children}
    </UiSettingsContext.Provider>
  );
}

export function useUiSettings(): UiSettingsSlice {
  const value = useContext(UiSettingsContext);
  if (!value)
    throw new Error("useUiSettings must be used inside UiSettingsProvider");
  return value;
}

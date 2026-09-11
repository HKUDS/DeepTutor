"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useSettings, type SettingsContextValue } from "./SettingsStore";

type SettingsDraftSlice = Pick<
  SettingsContextValue,
  | "hasUnsavedChanges"
  | "saving"
  | "applying"
  | "saveDraft"
  | "applyCatalog"
  | "applyService"
  | "discardDraft"
  | "storedDraft"
  | "draftState"
  | "draftRevision"
  | "pendingExtensionPayload"
  | "registerExtension"
>;

const SettingsDraftContext = createContext<SettingsDraftSlice | null>(null);

export function SettingsDraftProvider({ children }: { children: ReactNode }) {
  const source = useSettings();
  const value = useMemo<SettingsDraftSlice>(
    () => ({
      hasUnsavedChanges: source.hasUnsavedChanges,
      saving: source.saving,
      applying: source.applying,
      saveDraft: source.saveDraft,
      applyCatalog: source.applyCatalog,
      applyService: source.applyService,
      discardDraft: source.discardDraft,
      storedDraft: source.storedDraft,
      draftState: source.draftState,
      draftRevision: source.draftRevision,
      pendingExtensionPayload: source.pendingExtensionPayload,
      registerExtension: source.registerExtension,
    }),
    [
      source.hasUnsavedChanges,
      source.saving,
      source.applying,
      source.saveDraft,
      source.applyCatalog,
      source.applyService,
      source.discardDraft,
      source.storedDraft,
      source.draftState,
      source.draftRevision,
      source.pendingExtensionPayload,
      source.registerExtension,
    ],
  );
  return (
    <SettingsDraftContext.Provider value={value}>
      {children}
    </SettingsDraftContext.Provider>
  );
}

export function useSettingsDraft(): SettingsDraftSlice {
  const value = useContext(SettingsDraftContext);
  if (!value)
    throw new Error(
      "useSettingsDraft must be used inside SettingsDraftProvider",
    );
  return value;
}

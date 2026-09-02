"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useSettings, type SettingsContextValue } from "./SettingsStore";

type ModelCatalogSlice = Pick<
  SettingsContextValue,
  | "catalog"
  | "draft"
  | "providers"
  | "catalogEditable"
  | "mutateCatalog"
  | "addProfile"
  | "removeActiveProfile"
  | "addModel"
  | "removeActiveModel"
  | "updateProfileField"
  | "updateModelField"
  | "updateModelBoolField"
  | "updateContextWindowField"
  | "updateReasoningEffort"
  | "connectionTargets"
  | "connectionTarget"
  | "addConnection"
  | "updateConnectionField"
  | "removeConnection"
  | "unlinkProfile"
  | "linkConnectionToServices"
  | "llmContextDetection"
  | "applyDetectedContextWindow"
  | "embeddingCapabilities"
  | "embeddingDefaultDim"
>;

const ModelCatalogContext = createContext<ModelCatalogSlice | null>(null);

export function ModelCatalogProvider({ children }: { children: ReactNode }) {
  const source = useSettings();
  const value = useMemo<ModelCatalogSlice>(
    () => ({
      catalog: source.catalog,
      draft: source.draft,
      providers: source.providers,
      catalogEditable: source.catalogEditable,
      mutateCatalog: source.mutateCatalog,
      addProfile: source.addProfile,
      removeActiveProfile: source.removeActiveProfile,
      addModel: source.addModel,
      removeActiveModel: source.removeActiveModel,
      updateProfileField: source.updateProfileField,
      updateModelField: source.updateModelField,
      updateModelBoolField: source.updateModelBoolField,
      updateContextWindowField: source.updateContextWindowField,
      updateReasoningEffort: source.updateReasoningEffort,
      connectionTargets: source.connectionTargets,
      connectionTarget: source.connectionTarget,
      addConnection: source.addConnection,
      updateConnectionField: source.updateConnectionField,
      removeConnection: source.removeConnection,
      unlinkProfile: source.unlinkProfile,
      linkConnectionToServices: source.linkConnectionToServices,
      llmContextDetection: source.llmContextDetection,
      applyDetectedContextWindow: source.applyDetectedContextWindow,
      embeddingCapabilities: source.embeddingCapabilities,
      embeddingDefaultDim: source.embeddingDefaultDim,
    }),
    [
      source.catalog,
      source.draft,
      source.providers,
      source.catalogEditable,
      source.mutateCatalog,
      source.addProfile,
      source.removeActiveProfile,
      source.addModel,
      source.removeActiveModel,
      source.updateProfileField,
      source.updateModelField,
      source.updateModelBoolField,
      source.updateContextWindowField,
      source.updateReasoningEffort,
      source.connectionTargets,
      source.connectionTarget,
      source.addConnection,
      source.updateConnectionField,
      source.removeConnection,
      source.unlinkProfile,
      source.linkConnectionToServices,
      source.llmContextDetection,
      source.applyDetectedContextWindow,
      source.embeddingCapabilities,
      source.embeddingDefaultDim,
    ],
  );
  return (
    <ModelCatalogContext.Provider value={value}>
      {children}
    </ModelCatalogContext.Provider>
  );
}

export function useModelCatalog(): ModelCatalogSlice {
  const value = useContext(ModelCatalogContext);
  if (!value)
    throw new Error("useModelCatalog must be used inside ModelCatalogProvider");
  return value;
}

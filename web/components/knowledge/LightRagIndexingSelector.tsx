"use client";

import type {
  LightRagConfig,
  LightRagIndexingSelection,
} from "@/features/knowledge/model/types";
import type { LLMOption, LLMOptionsResponse } from "@/lib/llm-options";
import { selectionFromLightRagDefault } from "./IndexingModelSelector";
import { resolvedRole } from "./LightRagRoleModelsEditor";

export function indexingSelectionFromDefaults(
  options: LLMOption[],
  config: Pick<
    LightRagConfig,
    "llm_profile_id" | "llm_model_id" | "role_models"
  > & { version?: number },
  active?: LLMOptionsResponse["active"],
): LightRagIndexingSelection | null {
  if (config.role_models) {
    const extract = resolvedRole(config.role_models, "extract");
    const vlm = resolvedRole(config.role_models, "vlm");
    return extract
      ? {
          extract,
          vlm: vlm ? { mode: "enabled", selection: vlm } : { mode: "disabled" },
        }
      : null;
  }
  const selected = selectionFromLightRagDefault(options, config, active);
  if (!selected) return null;
  const vision =
    config.version !== 2 &&
    options.find(
      (option) =>
        option.profile_id === selected.profile_id &&
        option.model_id === selected.model_id,
    )?.supports_vision === true;
  return {
    extract: selected,
    vlm: vision
      ? { mode: "enabled", selection: selected }
      : { mode: "disabled" },
  };
}

export function isCompleteIndexingSelection(
  value: LightRagIndexingSelection | null,
  options?: LLMOption[],
): value is LightRagIndexingSelection {
  const structurallyComplete = Boolean(
    value?.extract.profile_id &&
    value.extract.model_id &&
    (value.vlm.mode === "disabled" ||
      (value.vlm.selection?.profile_id && value.vlm.selection.model_id)),
  );
  if (!structurallyComplete || !value || options === undefined) {
    return structurallyComplete;
  }
  const available = (selection: { profile_id: string; model_id: string }) =>
    options.find(
      (option) =>
        option.profile_id === selection.profile_id &&
        option.model_id === selection.model_id,
    );
  if (!available(value.extract)) return false;
  return (
    value.vlm.mode === "disabled" ||
    Boolean(
      value.vlm.selection && available(value.vlm.selection)?.supports_vision,
    )
  );
}

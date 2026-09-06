"use client";

import { useTranslation } from "react-i18next";
import type {
  LightRagConfig,
  LightRagIndexingSelection,
} from "@/features/knowledge/model/types";
import type { LLMOption, LLMOptionsResponse } from "@/lib/llm-options";
import type { LightRagIndexingPolicy } from "@/lib/knowledge-helpers";
import IndexingModelSelector, {
  selectionFromLightRagDefault,
} from "./IndexingModelSelector";
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

export function indexingSelectionFromPolicy(
  policy?: LightRagIndexingPolicy,
): LightRagIndexingSelection | null {
  if (policy?.schema_version === 2 && policy.extract?.selection && policy.vlm) {
    const extract = policy.extract.selection;
    if (policy.vlm.mode === "disabled")
      return { extract, vlm: { mode: "disabled" } };
    if (policy.vlm.mode === "enabled" && policy.vlm.snapshot?.selection)
      return {
        extract,
        vlm: { mode: "enabled", selection: policy.vlm.snapshot.selection },
      };
    return null;
  }
  if (policy?.selection && typeof policy.vision_available === "boolean") {
    return {
      extract: policy.selection,
      vlm: policy.vision_available
        ? { mode: "enabled", selection: policy.selection }
        : { mode: "disabled" },
    };
  }
  return null;
}

export function isCompleteIndexingSelection(
  value: LightRagIndexingSelection | null,
): value is LightRagIndexingSelection {
  return Boolean(
    value?.extract.profile_id &&
    value.extract.model_id &&
    (value.vlm.mode === "disabled" ||
      (value.vlm.selection?.profile_id && value.vlm.selection.model_id)),
  );
}

export default function LightRagIndexingSelector({
  options,
  selection,
  onChange,
  ...state
}: {
  options: LLMOption[];
  selection: LightRagIndexingSelection | null;
  onChange: (value: LightRagIndexingSelection | null) => void;
  loading: boolean;
  error: boolean;
  defaultUnavailable?: boolean;
  defaultLoadError?: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <p className="text-xs text-[var(--muted-foreground)]">
        {t(
          "Prefilled from the engine's EXTRACT and VLM settings. Changes here apply only to this new or rebuilt index.",
        )}
      </p>
      <IndexingModelSelector
        {...state}
        label="EXTRACT model"
        options={options}
        selection={selection?.extract ?? null}
        onChange={(extract) =>
          onChange(
            extract
              ? { extract, vlm: selection?.vlm ?? { mode: "disabled" } }
              : null,
          )
        }
      />
      {selection && (
        <>
          <label className="block text-xs">
            {t("VLM image analysis")}
            <select
              aria-label={t("VLM image analysis")}
              value={selection.vlm.mode}
              disabled={state.disabled}
              onChange={(event) => {
                onChange({
                  ...selection,
                  vlm:
                    event.target.value === "enabled"
                      ? { mode: "enabled" }
                      : { mode: "disabled" },
                });
              }}
              className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
            >
              <option value="disabled">{t("Image analysis disabled")}</option>
              <option value="enabled">{t("Choose a vision model")}</option>
            </select>
          </label>
          {selection.vlm.mode === "enabled" && (
            <IndexingModelSelector
              {...state}
              label="VLM model"
              options={options.filter((option) => option.supports_vision)}
              selection={selection.vlm.selection ?? null}
              onChange={(vlm) =>
                onChange({
                  ...selection,
                  vlm: { mode: "enabled", ...(vlm ? { selection: vlm } : {}) },
                })
              }
            />
          )}
          <p className="text-xs text-[var(--muted-foreground)]">
            {t(
              "After publication, enabling, disabling or replacing VLM requires a full rebuild. A VLM pinned now can process later image uploads.",
            )}
          </p>
        </>
      )}
    </div>
  );
}

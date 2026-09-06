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

export default function LightRagIndexingSelector({
  options,
  selection,
  defaults,
  collapsible = false,
  onChange,
  ...state
}: {
  options: LLMOption[];
  selection: LightRagIndexingSelection | null;
  defaults?: LightRagIndexingSelection | null;
  collapsible?: boolean;
  onChange: (value: LightRagIndexingSelection | null) => void;
  loading: boolean;
  error: boolean;
  defaultUnavailable?: boolean;
  defaultLoadError?: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const optionFor = (value?: { profile_id: string; model_id: string }) =>
    options.find(
      (option) =>
        option.profile_id === value?.profile_id &&
        option.model_id === value?.model_id,
    );
  const optionName = (value?: { profile_id: string; model_id: string }) => {
    const option = optionFor(value);
    return option?.model_name ?? value?.model_id ?? t("Not selected");
  };
  const optionLabel = (value?: { profile_id: string; model_id: string }) => {
    const option = optionFor(value);
    return option
      ? `${option.provider_label || option.profile_name} · ${option.model_name}`
      : (value?.model_id ?? t("Not selected"));
  };
  const sameSelection = (
    left?: { profile_id: string; model_id: string; reasoning_effort?: string },
    right?: { profile_id: string; model_id: string; reasoning_effort?: string },
  ) =>
    Boolean(
      left &&
        right &&
        left.profile_id === right.profile_id &&
        left.model_id === right.model_id &&
        (left.reasoning_effort ?? "") === (right.reasoning_effort ?? ""),
    );
  const usesDefaultVlm = Boolean(
    selection &&
      defaults &&
      selection.vlm.mode === defaults.vlm.mode &&
      (selection.vlm.mode === "disabled" ||
        (defaults.vlm.mode === "enabled" &&
          sameSelection(selection.vlm.selection, defaults.vlm.selection))),
  );
  const vlmValue = usesDefaultVlm
    ? "__engine_default__"
    : selection?.vlm.mode === "enabled" && selection.vlm.selection
      ? `${selection.vlm.selection.profile_id}:${selection.vlm.selection.model_id}`
      : "disabled";
  const defaultVlmLabel =
    defaults?.vlm.mode === "enabled"
      ? optionLabel(defaults.vlm.selection)
      : t("Image analysis disabled");
  const hasUnavailableSelection = Boolean(
    selection &&
    isCompleteIndexingSelection(selection) &&
    !isCompleteIndexingSelection(selection, options),
  );

  const fields = (
    <div className="space-y-4">
      <p className="text-xs text-[var(--muted-foreground)]">
        {t(
          defaults
            ? "Engine model settings are used by default. The resolved models are pinned when this index is created."
            : "Prefilled from the engine's EXTRACT and VLM settings. Changes here apply only to this new or rebuilt index.",
        )}
      </p>
      <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "Used to extract entities and relationships during indexing. Choose a fast, economical model with reasoning disabled.",
        )}
      </p>
      {hasUnavailableSelection && (
        <p className="text-xs text-red-600">
          {t(
            "One or more selected indexing models are unavailable. Choose accessible models before continuing.",
          )}
        </p>
      )}
      <IndexingModelSelector
        {...state}
        label="EXTRACT model"
        defaultSelection={defaults?.extract}
        defaultLabel={
          defaults
            ? `${t("Use engine default")} · ${optionLabel(defaults.extract)}`
            : undefined
        }
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
          <div className="space-y-1">
            <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "Used to analyze images during indexing. The model must support image input.",
              )}
            </p>
          </div>
          <label className="block text-xs font-medium">
            {t("VLM image analysis")}
            <select
              aria-label={t("VLM image analysis")}
              value={vlmValue}
              disabled={state.disabled}
              onChange={(event) => {
                if (event.target.value === "__engine_default__" && defaults) {
                  onChange({ ...selection, vlm: defaults.vlm });
                  return;
                }
                if (event.target.value === "disabled") {
                  onChange({ ...selection, vlm: { mode: "disabled" } });
                  return;
                }
                const option = options.find(
                  (item) =>
                    `${item.profile_id}:${item.model_id}` === event.target.value,
                );
                if (!option) return;
                onChange({
                  ...selection,
                  vlm: {
                    mode: "enabled",
                    selection: {
                      profile_id: option.profile_id,
                      model_id: option.model_id,
                    },
                  },
                });
              }}
              className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
            >
              {defaults && (
                <option value="__engine_default__">
                  {t("Use engine default")} · {defaultVlmLabel}
                </option>
              )}
              <option value="disabled">{t("Image analysis disabled")}</option>
              {options
                .filter((option) => option.supports_vision)
                .map((option) => (
                  <option
                    key={`${option.profile_id}:${option.model_id}`}
                    value={`${option.profile_id}:${option.model_id}`}
                  >
                    {option.provider_label || option.profile_name} ·{" "}
                    {option.model_name}
                  </option>
                ))}
            </select>
          </label>
          {selection.vlm.mode === "enabled" && selection.vlm.selection && (
            <IndexingModelSelector
              {...state}
              reasoningOnly
              options={options.filter((option) => option.supports_vision)}
              selection={selection.vlm.selection}
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
              defaults
                ? "After creation, changing EXTRACT or enabling, disabling, or replacing VLM requires a full rebuild."
                : "After publication, enabling, disabling or replacing VLM requires a full rebuild. A VLM pinned now can process later image uploads.",
            )}
          </p>
        </>
      )}
    </div>
  );

  if (!collapsible) return fields;
  const summary = selection
    ? `EXTRACT: ${optionName(selection.extract)} · VLM: ${
        selection.vlm.mode === "enabled"
          ? optionName(selection.vlm.selection)
          : t("Image analysis disabled")
      }`
    : t("Choose indexing models");
  return (
    <details
      className="rounded-xl border border-[var(--border)] bg-[var(--muted)]/20 p-3"
      open={
        state.error || state.defaultLoadError || !selection ? true : undefined
      }
    >
      <summary className="cursor-pointer list-none">
        <span className="block text-[12px] font-medium text-[var(--foreground)]">
          {t("Indexing models (optional override)")}
        </span>
        <span className="mt-1 block text-[11px] text-[var(--muted-foreground)]">
          {summary}
        </span>
      </summary>
      <div className="mt-4 border-t border-[var(--border)] pt-4">{fields}</div>
    </details>
  );
}

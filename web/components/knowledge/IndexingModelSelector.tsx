"use client";

import { useTranslation } from "react-i18next";
import type {
  IndexingLLMSelection,
  LightRagConfig,
} from "@/features/knowledge/model/types";
import type { LLMOption } from "@/lib/llm-options";
import {
  reasoningEffortOptions,
  reasoningEffortOptionsFromSupportedLevels,
} from "@/lib/reasoning-effort";

const INDEXING_REASONING_EFFORTS = new Set([
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
  "adaptive",
]);

export function selectionFromLLMOption(
  option: LLMOption,
  reasoningEffort = "",
): IndexingLLMSelection {
  const selection: IndexingLLMSelection = {
    profile_id: option.profile_id,
    model_id: option.model_id,
  };
  // `none` is meaningful and must remain present; only the empty inherited
  // value is omitted from the request.
  if (reasoningEffort) selection.reasoning_effort = reasoningEffort;
  return selection;
}

export function selectionFromLightRagDefault(
  options: LLMOption[],
  config: Pick<LightRagConfig, "llm_profile_id" | "llm_model_id">,
  activeDefault?: {
    profile_id?: string | null;
    model_id?: string | null;
  } | null,
): IndexingLLMSelection | null {
  const hasDedicated = Boolean(config.llm_profile_id || config.llm_model_id);
  const profileId = hasDedicated
    ? config.llm_profile_id
    : activeDefault?.profile_id;
  const modelId = hasDedicated ? config.llm_model_id : activeDefault?.model_id;
  const option =
    hasDedicated || (profileId && modelId)
      ? options.find(
          (item) => item.profile_id === profileId && item.model_id === modelId,
        )
      : options.find((item) => item.is_active_default);
  return option ? selectionFromLLMOption(option) : null;
}

interface IndexingModelSelectorProps {
  label?: string;
  labelClassName?: string;
  defaultSelection?: IndexingLLMSelection | null;
  defaultLabel?: string;
  lockModel?: boolean;
  reasoningOnly?: boolean;
  inheritBaseReasoning?: string | null;
  options: LLMOption[];
  selection: IndexingLLMSelection | null;
  loading: boolean;
  error: boolean;
  defaultUnavailable?: boolean;
  defaultLoadError?: boolean;
  disabled?: boolean;
  onChange: (selection: IndexingLLMSelection | null) => void;
}

export default function IndexingModelSelector({
  label = "Indexing model",
  labelClassName = "text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]",
  defaultSelection,
  defaultLabel,
  lockModel = false,
  reasoningOnly = false,
  inheritBaseReasoning,
  options,
  selection,
  loading,
  error,
  defaultUnavailable = false,
  defaultLoadError = false,
  disabled = false,
  onChange,
}: IndexingModelSelectorProps) {
  const { t } = useTranslation();
  const selected = options.find(
    (option) =>
      option.profile_id === selection?.profile_id &&
      option.model_id === selection?.model_id,
  );
  const usesDefault = Boolean(
    defaultSelection &&
      selection?.profile_id === defaultSelection.profile_id &&
      selection?.model_id === defaultSelection.model_id &&
      (selection.reasoning_effort ?? "") ===
        (defaultSelection.reasoning_effort ?? ""),
  );
  const reasoningOptions = (
    selected
      ? selected.supported_reasoning_efforts !== undefined
        ? reasoningEffortOptionsFromSupportedLevels(
            selected.supported_reasoning_efforts,
          )
        : reasoningEffortOptions(
            selected.provider,
            selected.model,
            selection?.reasoning_effort || selected.reasoning_effort || "",
          )
      : []
  ).filter(
    (option) =>
      option.value === "" || INDEXING_REASONING_EFFORTS.has(option.value),
  );

  if (loading && options.length === 0) {
    return (
      <p className="text-[12px] text-[var(--muted-foreground)]">
        {t("Loading model catalog…")}
      </p>
    );
  }
  if (error && options.length === 0) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
        {t(
          "The model catalog could not be loaded. Check model settings and try again.",
        )}
      </div>
    );
  }
  if (options.length === 0) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
        {t("No indexing model is available. Configure an LLM model first.")}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {!reasoningOnly && <label className="block">
        <span className={`mb-1.5 block ${labelClassName}`}>
          {t(label)}
        </span>
        <select
          value={
            usesDefault
              ? "__engine_default__"
              : selected
                ? `${selected.profile_id}:${selected.model_id}`
                : ""
          }
          disabled={disabled || lockModel}
          onChange={(event) => {
            if (event.target.value === "__engine_default__") {
              onChange(defaultSelection ?? null);
              return;
            }
            const option = options.find(
              (item) =>
                `${item.profile_id}:${item.model_id}` === event.target.value,
            );
            onChange(option ? selectionFromLLMOption(option) : null);
          }}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] disabled:opacity-50"
        >
          <option value="" disabled>
            {t("Select an indexing model")}
          </option>
          {defaultSelection && defaultLabel && (
            <option value="__engine_default__">{defaultLabel}</option>
          )}
          {options.map((option) => (
            <option
              key={`${option.profile_id}:${option.model_id}`}
              value={`${option.profile_id}:${option.model_id}`}
            >
              {option.provider_label || option.profile_name} ·{" "}
              {option.model_name}
              {option.model_name !== option.model ? ` (${option.model})` : ""}
            </option>
          ))}
        </select>
      </label>}

      {!reasoningOnly && defaultUnavailable && !selection && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          {t(
            "The current LightRAG query model is unavailable here. Choose an accessible indexing model.",
          )}
        </div>
      )}
      {!reasoningOnly && defaultLoadError && !selection && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {t(
            "The LightRAG query-model setting could not be loaded. Choose an indexing model or try again.",
          )}
        </div>
      )}

      {selected &&
        (reasoningOptions.length > 0 || selection?.reasoning_effort) && (
          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
              {t("Reasoning effort")}
            </span>
            <select
              aria-label={t("Reasoning effort")}
              value={selection?.reasoning_effort ?? ""}
              disabled={disabled}
              onChange={(event) =>
                onChange(selectionFromLLMOption(selected, event.target.value))
              }
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] disabled:opacity-50"
            >
              <option value="">
                {inheritBaseReasoning !== undefined
                  ? t("Inherit base reasoning")
                  : t("Model default / unspecified")}
              </option>
              {selection?.reasoning_effort &&
                !reasoningOptions.some(
                  (option) => option.value === selection.reasoning_effort,
                ) && (
                  <option value={selection.reasoning_effort} disabled>
                    {t("Unsupported reasoning effort")}:{" "}
                    {selection.reasoning_effort}
                  </option>
                )}
              {reasoningOptions
                .filter((option) => option.value)
                .map((option) => (
                  <option key={option.value || "auto"} value={option.value}>
                    {t(option.label)}
                  </option>
                ))}
            </select>
            <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
              {t("Effective reasoning")}:{" "}
              {selection?.reasoning_effort ||
                inheritBaseReasoning ||
                selected.reasoning_effort ||
                t("Model default")}
              .{" "}
              {inheritBaseReasoning !== undefined
                ? t(
                    "With no role override, reasoning follows the LightRAG base.",
                  )
                : t(
                    "Auto inherits the selected model's saved reasoning effort.",
                  )}
            </p>
          </label>
        )}
    </div>
  );
}

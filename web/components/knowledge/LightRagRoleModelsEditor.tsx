"use client";

import { useTranslation } from "react-i18next";
import type {
  IndexingLLMSelection,
  LightRagRoleModel,
  LightRagRoleModels,
} from "@/features/knowledge/model/types";
import type { LLMOption } from "@/lib/llm-options";
import IndexingModelSelector from "./IndexingModelSelector";

const ROLE_DESCRIPTIONS = {
  extract:
    "Used to extract entities and relationships during indexing. Choose a fast, economical model with reasoning disabled.",
  keyword:
    "Used to generate retrieval keywords before a query. Choose a fast model with reasoning disabled.",
  query:
    "Used to produce the final answer from long, complex retrieval context. Choose a capable model; reasoning can be enabled.",
  vlm: "Used to analyze images during indexing. The model must support image input.",
} as const;

export const inheritedRole = (maxAsync = 4): LightRagRoleModel => ({
  mode: "inherit",
  max_async: maxAsync,
  timeout: 240,
});
export const newRoleModels = (
  base: IndexingLLMSelection,
  vision = false,
  maxAsync = 4,
): LightRagRoleModels => ({
  base,
  extract: inheritedRole(maxAsync),
  keyword: inheritedRole(maxAsync),
  query: inheritedRole(maxAsync),
  vlm: {
    ...inheritedRole(maxAsync),
    mode: vision ? "inherit" : "disabled",
  },
});

export function roleModelsValidationError(
  models: LightRagRoleModels | null,
  options: LLMOption[],
): string | null {
  if (!models) return "Choose a LightRAG base model before saving.";
  const findOption = (selection: IndexingLLMSelection | null | undefined) =>
    options.find(
      (option) =>
        option.profile_id === selection?.profile_id &&
        option.model_id === selection?.model_id,
    );
  const baseOption = findOption(models.base);
  if (!baseOption) {
    return "The LightRAG base model is unavailable. Choose an accessible model.";
  }
  if (
    models.base.reasoning_effort &&
    !baseOption.supported_reasoning_efforts?.includes(
      models.base.reasoning_effort,
    )
  ) {
    return "The selected reasoning effort is no longer supported.";
  }
  for (const role of ["extract", "keyword", "query", "vlm"] as const) {
    const value = models[role];
    if (
      !Number.isInteger(value.max_async) ||
      value.max_async < 1 ||
      value.max_async > 32 ||
      !Number.isInteger(value.timeout) ||
      value.timeout < 1 ||
      value.timeout > 3600
    ) {
      return "Concurrency and timeout values must stay within the displayed limits.";
    }
    const effective = resolvedRole(models, role);
    if (!effective) continue;
    const option = findOption(effective);
    if (!option) {
      return "One or more role models are unavailable. Choose accessible models before saving.";
    }
    if (role === "vlm" && option.supports_vision !== true) {
      return "The selected VLM model does not support image inputs.";
    }
    if (
      effective.reasoning_effort &&
      !option.supported_reasoning_efforts?.includes(
        effective.reasoning_effort,
      )
    ) {
      return "The selected reasoning effort is no longer supported.";
    }
  }
  return null;
}

export function resolvedRole(
  models: LightRagRoleModels,
  role: "extract" | "keyword" | "query" | "vlm",
): IndexingLLMSelection | null {
  const value = models[role];
  if (value.mode === "disabled") return null;
  const selected = value.mode === "inherit" ? models.base : value.selection;
  if (!selected) return null;
  return {
    ...selected,
    ...(value.reasoning_effort
      ? { reasoning_effort: value.reasoning_effort }
      : {}),
  };
}

export default function LightRagRoleModelsEditor({
  models,
  options,
  initialMaxAsync,
  loading,
  error,
  disabled,
  onChange,
}: {
  models: LightRagRoleModels | null;
  options: LLMOption[];
  initialMaxAsync?: number;
  loading: boolean;
  error: boolean;
  disabled?: boolean;
  onChange: (value: LightRagRoleModels) => void;
}) {
  const { t } = useTranslation();
  const baseOption = options.find(
    (option) =>
      option.profile_id === models?.base.profile_id &&
      option.model_id === models?.base.model_id,
  );
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <IndexingModelSelector
          label="LightRAG base model"
          description="The default model when no role model is specified. Role models can inherit its model and reasoning setting."
          labelClassName="text-[12px] font-medium text-[var(--foreground)]"
          options={options}
          selection={models?.base ?? null}
          loading={loading}
          error={error}
          disabled={disabled}
          onChange={(base) => {
            if (base)
              onChange(
                models
                  ? { ...models, base }
                  : newRoleModels(base, false, initialMaxAsync),
              );
          }}
        />
        {baseOption && (
          <p className="text-[11px] text-[var(--muted-foreground)]">
            {t("Currently effective")}: {baseOption.provider_label || baseOption.profile_name} ·{" "}
            {baseOption.model_name} ·{" "}
            {models?.base.reasoning_effort || t("Auto")}
          </p>
        )}
      </div>
      {models &&
        (["extract", "keyword", "query", "vlm"] as const).map((role) => {
          const value = models[role];
          const effective = resolvedRole(models, role);
          const roleOptions =
            role === "vlm"
              ? options.filter((option) => option.supports_vision)
              : options;
          const effectiveOption = options.find(
            (option) =>
              option.profile_id === effective?.profile_id &&
              option.model_id === effective?.model_id,
          );
          const selectionKey =
            value.mode === "model" && value.selection
              ? `${value.selection.profile_id}:${value.selection.model_id}`
              : value.mode;
          const update = (patch: Partial<LightRagRoleModel>) =>
            onChange({ ...models, [role]: { ...value, ...patch } });
          return (
            <fieldset
              key={role}
              className="space-y-3 rounded-lg border border-[var(--border)] p-3"
              disabled={disabled}
            >
              <legend className="px-1 text-[12px] font-medium text-[var(--foreground)]">
                {role.toUpperCase()}
              </legend>
              <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                {t(ROLE_DESCRIPTIONS[role])}
              </p>
              <label className="block text-xs font-medium">
                {t("Model")}
                <select
                  aria-label={`${role.toUpperCase()} ${t("Model")}`}
                  value={selectionKey}
                  className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
                  onChange={(event) => {
                    const next = event.target.value;
                    if (next === "disabled" || next === "inherit") {
                      update({
                        mode: next,
                        selection: null,
                        reasoning_effort: null,
                      });
                      return;
                    }
                    const option = roleOptions.find(
                      (item) =>
                        `${item.profile_id}:${item.model_id}` === next,
                    );
                    if (option) {
                      update({
                        mode: "model",
                        selection: {
                          profile_id: option.profile_id,
                          model_id: option.model_id,
                        },
                        reasoning_effort: null,
                      });
                    }
                  }}
                >
                  {role === "vlm" && (
                    <option value="disabled">
                      {t("Image analysis disabled")}
                    </option>
                  )}
                  <option
                    value="inherit"
                    disabled={
                      role === "vlm" && baseOption?.supports_vision !== true
                    }
                  >
                    {t("Inherit LightRAG base model")} ·{" "}
                    {options.find(
                      (option) =>
                        option.profile_id === models.base.profile_id &&
                        option.model_id === models.base.model_id,
                    )?.model_name ?? models.base.model_id}
                  </option>
                  {value.mode === "model" &&
                    value.selection &&
                    !roleOptions.some(
                      (option) =>
                        option.profile_id === value.selection?.profile_id &&
                        option.model_id === value.selection?.model_id,
                    ) && (
                      <option value={selectionKey} disabled>
                        {t("Unavailable model")} · {value.selection.model_id}
                      </option>
                    )}
                  {roleOptions.map((option) => (
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
              {value.mode !== "disabled" && (
                <IndexingModelSelector
                  reasoningOnly
                  showReasoningHint={false}
                  options={roleOptions}
                  selection={
                    effective
                      ? {
                          ...effective,
                          reasoning_effort: value.reasoning_effort ?? undefined,
                        }
                      : null
                  }
                  inheritBaseReasoning={
                    value.mode === "inherit"
                      ? (models.base.reasoning_effort ?? null)
                      : undefined
                  }
                  loading={loading}
                  error={error}
                  onChange={(selection) => {
                    if (selection)
                      update({
                        selection:
                          value.mode === "model"
                            ? {
                                profile_id: selection.profile_id,
                                model_id: selection.model_id,
                              }
                            : null,
                        reasoning_effort: selection.reasoning_effort ?? null,
                      });
                  }}
                />
              )}
              {effectiveOption && value.mode !== "disabled" && (
                <p className="text-[11px] text-[var(--muted-foreground)]">
                  {t("Currently effective")}: {effectiveOption.provider_label || effectiveOption.profile_name} ·{" "}
                  {effectiveOption.model_name} ·{" "}
                  {effective?.reasoning_effort || t("Auto")}
                </p>
              )}
              {role === "vlm" &&
                value.mode !== "disabled" &&
                !options.some(
                  (option) =>
                    option.profile_id === effective?.profile_id &&
                    option.model_id === effective?.model_id &&
                    option.supports_vision,
                ) && (
                  <p className="text-xs text-red-600">
                    {t("The selected VLM model does not support image inputs.")}
                  </p>
                )}
              {value.mode !== "disabled" && (
                <details className="rounded-lg border border-[var(--border)] px-3 py-2">
                  <summary className="cursor-pointer text-xs font-medium">
                    {t("Advanced")}
                  </summary>
                  <div className="mt-3 grid grid-cols-2 gap-3">
                  <label className="text-xs">
                    {t("Concurrent LLM calls")}
                    <input
                      aria-label={`${role.toUpperCase()} ${t("Concurrent LLM calls")}`}
                      type="number"
                      min={1}
                      max={32}
                      value={value.max_async}
                      onChange={(event) =>
                        update({ max_async: Number(event.target.value) })
                      }
                      className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--background)] p-2"
                    />
                  </label>
                  <label className="text-xs">
                    {t("Timeout (seconds)")}
                    <input
                      aria-label={`${role.toUpperCase()} ${t("Timeout (seconds)")}`}
                      type="number"
                      min={1}
                      max={3600}
                      value={value.timeout}
                      onChange={(event) =>
                        update({ timeout: Number(event.target.value) })
                      }
                      className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--background)] p-2"
                    />
                  </label>
                  </div>
                </details>
              )}
            </fieldset>
          );
        })}
    </div>
  );
}

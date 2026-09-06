"use client";

import { useTranslation } from "react-i18next";
import type {
  IndexingLLMSelection,
  LightRagRoleModel,
  LightRagRoleModels,
} from "@/features/knowledge/model/types";
import type { LLMOption } from "@/lib/llm-options";
import IndexingModelSelector from "./IndexingModelSelector";

export const inheritedRole = (): LightRagRoleModel => ({
  mode: "inherit",
  max_async: 4,
  timeout: 240,
});
export const newRoleModels = (
  base: IndexingLLMSelection,
  vision = false,
): LightRagRoleModels => ({
  base,
  extract: inheritedRole(),
  keyword: inheritedRole(),
  query: inheritedRole(),
  vlm: { ...inheritedRole(), mode: vision ? "inherit" : "disabled" },
});

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
  loading,
  error,
  disabled,
  onChange,
}: {
  models: LightRagRoleModels | null;
  options: LLMOption[];
  loading: boolean;
  error: boolean;
  disabled?: boolean;
  onChange: (value: LightRagRoleModels) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <IndexingModelSelector
        label="LightRAG base model"
        options={options}
        selection={models?.base ?? null}
        loading={loading}
        error={error}
        disabled={disabled}
        onChange={(base) => {
          if (base)
            onChange(models ? { ...models, base } : newRoleModels(base));
        }}
      />
      {models &&
        (["extract", "keyword", "query", "vlm"] as const).map((role) => {
          const value = models[role];
          const effective = resolvedRole(models, role);
          const update = (patch: Partial<LightRagRoleModel>) =>
            onChange({ ...models, [role]: { ...value, ...patch } });
          return (
            <fieldset
              key={role}
              className="space-y-3 rounded-lg border border-[var(--border)] p-3"
              disabled={disabled}
            >
              <legend className="px-1 text-sm font-medium">
                {role.toUpperCase()}
              </legend>
              <label className="block text-xs">
                {t("Model source")}
                <select
                  aria-label={`${role.toUpperCase()} ${t("Model source")}`}
                  value={value.mode}
                  className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
                  onChange={(event) => {
                    const mode = event.target
                      .value as LightRagRoleModel["mode"];
                    update({
                      mode,
                      selection:
                        mode === "model"
                          ? {
                              profile_id: models.base.profile_id,
                              model_id: models.base.model_id,
                            }
                          : null,
                      reasoning_effort: null,
                    });
                  }}
                >
                  {role === "vlm" && (
                    <option value="disabled">
                      {t("Image analysis disabled")}
                    </option>
                  )}
                  <option value="inherit">
                    {t("Inherit LightRAG base model")}
                  </option>
                  <option value="model">{t("Choose a model")}</option>
                </select>
              </label>
              {value.mode !== "disabled" && (
                <IndexingModelSelector
                  label={`${role.toUpperCase()} ${t("effective model")}`}
                  options={
                    role === "vlm" && value.mode === "model"
                      ? options.filter((option) => option.supports_vision)
                      : options
                  }
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
                  lockModel={value.mode === "inherit"}
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
                <div className="grid grid-cols-2 gap-3">
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
              )}
            </fieldset>
          );
        })}
    </div>
  );
}

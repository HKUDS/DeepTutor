"use client";

import { useTranslation } from "react-i18next";
import { ServiceConfigEditor } from "./ServiceConfigEditor";
import { ModelTestPanel } from "./ModelTestPanel";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { selectClass } from "./shared";

/** Optional task references leave every legacy profile and credential intact. */
export function TaskModelsEditor() {
  const { t } = useTranslation();
  const { draft, catalogEditable, mutateCatalog } =
    useSettings();
  const task = draft.services.task;
  const mode = task.mode ?? (task.profiles.length ? "profiles" : "inherit");
  const options = draft.services.llm.profiles.flatMap((profile) =>
    profile.models
      .filter((model) => model.model)
      .map((model) => ({
        profile,
        model,
        value: JSON.stringify([profile.id, model.id]),
      })),
  );
  const selected = options.find(
    (item) =>
      item.profile.id === task.selection?.profile_id &&
      item.model.id === task.selection?.model_id,
  );
  const value =
    mode === "reference" ? (selected?.value ?? "missing") : mode;
  if (!catalogEditable) return <ServiceConfigEditor service="task" />;
  return (
    <div className="space-y-5">
      <p className="text-sm text-[var(--muted-foreground)]">
        {t(
          "Conversation titles and starting suggestions can use a smaller model from a provider you already configured.",
        )}
      </p>
      <label className="block space-y-2 text-sm font-medium">
        {t("Task model")}
        <select
          className={selectClass}
          aria-label={t("Task model")}
          value={value}
          onChange={(event) => {
            const value = event.target.value;
            mutateCatalog((next) => {
              if (value === "inherit" || value === "profiles")
                next.services.task.mode = value;
              else {
                const [profile_id, model_id] = JSON.parse(value) as [
                  string,
                  string,
                ];
                next.services.task.mode = "reference";
                next.services.task.selection = { profile_id, model_id };
              }
            });
          }}
        >
          <option value="inherit">{t("Follow the chat model")}</option>
          {mode === "reference" && !selected && (
            <option value="missing" disabled>
              {t("Selected model is unavailable — choose another")}
            </option>
          )}
          {options.map((item) => (
            <option key={item.value} value={item.value}>
              {item.profile.name} · {item.model.name || item.model.model}
            </option>
          ))}
          <option value="profiles">
            {t("Use a separate task provider")}
          </option>
        </select>
      </label>
      {mode !== "profiles" && (
        <>
          {mode === "reference" && selected && (
            <ModelTestPanel
              service="llm"
              profile={selected.profile}
              model={selected.model}
            />
          )}
          <p className="text-xs text-[var(--muted-foreground)]">
            {t(
              "Provider credentials are reused. Your previously configured task providers are kept when switching modes.",
            )}
          </p>
        </>
      )}

      {mode === "profiles" && <ServiceConfigEditor service="task" />}
    </div>
  );
}

export default TaskModelsEditor;

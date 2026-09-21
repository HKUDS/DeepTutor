"use client";

import Link from "next/link";
import { stageRegistryAction, type RegistryEdit } from "@/lib/provider-registry";
import { useTranslation } from "react-i18next";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { flattenModels, modelProvider } from "@/lib/provider-registry";
import { SettingRow, SettingSection, selectClass } from "./shared";

/**
 * The background task model, and the tasks that run on it.
 *
 * DeepTutor makes a dozen small calls nobody asked for — a conversation title,
 * the starter chips, a composer hint, a vocabulary lookup. They used to share a
 * single selector tucked under the language model list, which said nothing about
 * *what* it governed: the page named one model and left the reader to guess
 * which of the product's behaviours changed when they moved it. So the tasks are
 * listed here by name, each able to name its own model, with one global choice
 * above them for the (common) case where they should all agree.
 *
 * A task with no choice of its own follows the global one. That is the absence
 * of a row in `services.task.overrides`, not a fourth mode — see the backend's
 * `TaskKind` module — so the list below has exactly one default and no way for
 * two records of it to drift apart.
 *
 * Every select applies immediately rather than staging a draft. A model pointer
 * is one field with no partial state to review, and applying means the control
 * can only ever show what is actually running: a rejected save leaves the
 * catalog untouched, so the select snaps back on its own.
 */

/** Follow the global task model — sent as a mode, stored as no override at all. */
const GLOBAL = "global";
/** Follow whatever model the conversation itself is running on. */
const INHERIT = "inherit";

/**
 * How each task reads on screen. Keyed by the backend's `TaskKind`; the backend
 * owns *which* tasks exist, this owns how to say them. A kind with no entry here
 * still gets a row (its id), because a task DeepTutor runs is worth configuring
 * before it is worth naming.
 */
const TASK_TEXT: Record<string, { label: string; detail: string }> = {
  session_title: {
    label: "Conversation titles",
    detail: "Names a conversation from its opening exchange.",
  },
  chat_starters: {
    label: "Starter suggestions",
    detail: "Writes the openings offered under an empty composer.",
  },
  chat_ask_hint: {
    label: "Composer hint",
    detail: "Predicts the line you are likely to type next.",
  },
  mastery_goal_name: {
    label: "Mastery goal names",
    detail: "Turns what you asked to learn into a short name.",
  },
  mastery_ask_hint: {
    label: "Study composer hint",
    detail: "Offers a question to ask about the current waypoint.",
  },
  reading_ask_hint: {
    label: "Reading composer hint",
    detail: "Offers a question grounded in the page you are on.",
  },
  reading_openers: {
    label: "Reading openers",
    detail: "Suggests what to discuss when a reading chat is still empty.",
  },
  reading_vocabulary: {
    label: "Vocabulary help",
    detail: "Explains a word or phrase you selected while reading.",
  },
  reading_translation: {
    label: "Translation",
    detail: "Translates a passage you selected while reading.",
  },
  reading_guidance: {
    label: "Study guidance",
    detail: "Suggests how to work through the section you are reading.",
  },
  reading_quiz: {
    label: "Reading questions",
    detail: "Writes practice questions from what you are reading.",
  },
};

/** Section heading per task group, in the order the backend returns them. */
const GROUP_TEXT: Record<string, string> = {
  chat: "Conversation",
  mastery: "Mastery path",
  reading: "Immersive reading",
};

type TaskChoice = NonNullable<RegistryEdit["task"]>;

/**
 * The select value a stored choice corresponds to.
 *
 * A half-written record reads as the fallback rather than as a broken pointer,
 * which is what the backend does with one too: a record it cannot resolve means
 * the default, so the two agree about what an incomplete choice means.
 */
function choiceValue(
  choice: {
    mode?: string;
    selection?: { profile_id: string; model_id: string };
    active_profile_id?: string | null;
    active_model_id?: string | null;
  } | null,
  fallback: string,
): string {
  if (!choice) return fallback;
  if (choice.mode === INHERIT) return INHERIT;
  if (choice.mode === "reference")
    return choice.selection?.profile_id && choice.selection?.model_id
      ? `llm:${choice.selection.profile_id}:${choice.selection.model_id}`
      : fallback;
  if (choice.mode === "profiles")
    return choice.active_profile_id && choice.active_model_id
      ? `task:${choice.active_profile_id}:${choice.active_model_id}`
      : fallback;
  return fallback;
}

export function TaskModelsWorkspace() {
  const { t } = useTranslation();
  const { draft: catalog, taskKinds, catalogEditable, mutateCatalog, applying } =
    useSettings();

  const stageRegistry = async (edit: RegistryEdit) => {
    mutateCatalog((next) => stageRegistryAction(next, edit));
    return true;
  };
  if (!catalogEditable)
    return (
      <p className="text-sm text-[var(--muted-foreground)]">
        {t("Only administrators can manage models.")}
      </p>
    );

  const task = catalog.services.task;
  const rows = flattenModels(catalog, ["llm", "task"]).filter(
    (row) => row.model?.model,
  );
  // Catalogs written before the task service had a `mode` say which model to use
  // by holding a task profile at all, so an absent mode means "profiles" there.
  const globalValue = choiceValue(
    { ...task, mode: task.mode ?? (task.profiles.length ? "profiles" : INHERIT) },
    INHERIT,
  );

  /** Turn a select value back into the edit that stores it. */
  const choiceFor = (value: string): TaskChoice | null => {
    if (value === GLOBAL) return { mode: GLOBAL };
    if (value === INHERIT) return { mode: INHERIT };
    const row = rows.find((item) => item.key === value);
    if (!row?.model) return null;
    return row.service === "llm"
      ? {
          mode: "reference",
          selection: { profile_id: row.profile.id, model_id: row.model.id },
        }
      : {
          mode: "profiles",
          active_profile_id: row.profile.id,
          active_model_id: row.model.id,
        };
  };

  const save = (value: string, taskKind?: string) => {
    const choice = choiceFor(value);
    if (!choice) return;
    void stageRegistry({
      kind: "task_choice",
      task: taskKind ? { ...choice, task_kind: taskKind } : choice,
    });
  };

  /**
   * One model select. `leading` is the option that heads the list — the global
   * choice offers the chat model, a task offers the global model — and doubles
   * as where an unresolvable pointer parks.
   */
  const modelSelect = (
    label: string,
    value: string,
    leading: { value: string; label: string },
    onPick: (value: string) => void,
  ) => {
    const known = value === leading.value || rows.some((r) => r.key === value);
    return (
      <select
        aria-label={label}
        className={`${selectClass} min-w-[16rem] max-w-full py-1.5 text-[13px]`}
        disabled={applying}
        value={known ? value : leading.value}
        onChange={(event) => onPick(event.target.value)}
      >
        <option value={leading.value}>{leading.label}</option>
        {!known && (
          <option value={value} disabled>
            {t("Selected model is unavailable — choose another")}
          </option>
        )}
        {rows.map((row) => (
          <option key={row.key} value={row.key}>
            {row.model!.name || row.model!.model} ·{" "}
            {modelProvider(catalog, row.service, row.profile, row.model)?.name ||
              t("Provider unavailable")}
          </option>
        ))}
      </select>
    );
  };

  // Group order follows the payload, so a new group appears where the backend
  // put it rather than wherever a hardcoded list happened to leave room.
  const groups: { group: string; kinds: string[] }[] = [];
  for (const kind of taskKinds) {
    const existing = groups.find((entry) => entry.group === kind.group);
    if (existing) existing.kinds.push(kind.id);
    else groups.push({ group: kind.group, kinds: [kind.id] });
  }

  return (
    <div>
      <SettingSection
        title={t("Global task model")}
        description={t(
          "Every call DeepTutor makes on its own runs here unless the task below names its own model.",
        )}
      >
        <SettingRow
          title={t("Background task model")}
          description={t(
            "A smaller, cheaper model is usually the right choice: these calls are short, frequent, and never the answer a learner is reading.",
          )}
          control={modelSelect(
            t("Background task model"),
            globalValue,
            { value: INHERIT, label: t("Follow the chat model") },
            (value) => save(value),
          )}
        />
        {!rows.length && (
          <p className="pb-3.5 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {t("No models configured yet.")}{" "}
            <Link
              href="/settings/llm"
              className="underline underline-offset-4 transition-colors hover:text-[var(--foreground)]"
            >
              {t("Add a language model")}
            </Link>
          </p>
        )}
      </SettingSection>

      {groups.map((entry) => (
        <SettingSection
          key={entry.group}
          title={t(GROUP_TEXT[entry.group] ?? entry.group)}
        >
          {entry.kinds.map((kind) => {
            const text = TASK_TEXT[kind];
            const label = text ? t(text.label) : kind;
            return (
              <SettingRow
                key={kind}
                title={label}
                description={text ? t(text.detail) : undefined}
                control={modelSelect(
                  label,
                  choiceValue(task.overrides?.[kind] ?? null, GLOBAL),
                  { value: GLOBAL, label: t("Follow the global task model") },
                  (value) => save(value, kind),
                )}
              />
            );
          })}
        </SettingSection>
      ))}
    </div>
  );
}

export default TaskModelsWorkspace;

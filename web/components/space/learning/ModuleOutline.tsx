"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Check,
  ChevronRight,
  Circle,
  CircleDot,
  Loader2,
  LockKeyhole,
  SkipForward,
  Sparkles,
  Undo2,
} from "lucide-react";

import {
  fetchObjectiveReport,
  type MapKnowledgePoint,
  type MasteryTopic,
  type ObjectiveReport,
} from "@/lib/learning-api";

import { knowledgeTypeLabel, topicDisplayName, type Translate } from "./format";
import { ObjectiveDetail } from "./ObjectiveDetail";

function statusLabel(point: MapKnowledgePoint, t: Translate) {
  if (point.mastery_source === "learner") return t("Marked as known");
  if (point.status === "mastered") return t("Mastered");
  if (point.deferred) return t("Deferred for now");
  if (point.status === "learning") return t("In progress");
  return t("Not started");
}

function StatusMark({ point }: { point: MapKnowledgePoint }) {
  // Fill -> ring -> outline. Progression stays legible without inventing a
  // success colour the product does not have, and without relying on hue
  // alone to carry the state.
  const base =
    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border";
  if (point.status === "mastered") {
    return (
      <span
        className={`${base} border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]`}
      >
        {point.mastery_source === "learner" ? (
          <Sparkles className="h-3 w-3" />
        ) : (
          <Check className="h-3.5 w-3.5" />
        )}
      </span>
    );
  }
  if (point.status === "learning") {
    return (
      <span
        className={`${base} border-[var(--primary)] bg-[var(--card)] text-[var(--primary)]`}
      >
        <CircleDot className="h-3.5 w-3.5" />
      </span>
    );
  }
  return (
    <span
      className={`${base} border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)]`}
    >
      <Circle className="h-3 w-3" />
    </span>
  );
}

/**
 * The topic's modules and knowledge points, as an outline.
 *
 * This replaced an illustrated route map. The map filled the page's main
 * column but the only thing you could do with it was click a point — the same
 * affordance a list row gives in a fraction of the space, while showing far
 * more of the topic at once.
 */
export function ModuleOutline({
  topic,
  revision,
  selectedId,
  zh,
  onSelect,
  onOverride,
  onDefer,
}: {
  topic: MasteryTopic;
  revision: number;
  selectedId: string | null;
  zh: boolean;
  onSelect: (id: string | null) => void;
  onOverride: (
    objectiveId: string,
    mastered: boolean,
    note: string,
  ) => Promise<void>;
  onDefer: (objectiveId: string, note: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const nextId = topic.next.knowledge_point_id;
  const topicName = topicDisplayName(topic, t);

  return (
    // One block per module rather than one list divided into modules. A
    // module is the unit the learner reasons about — it has its own objective,
    // its own progress, and it is what `mastery_revise` operates on. Blocks are
    // set apart by space and a heading, not by frames: ten framed modules read
    // as ten boxes before they read as an outline.
    <section id="mastery-outline-start" aria-label={t("Topic outline")}>
      {topic.map.modules.map((module, moduleIndex) => (
        <div key={module.id} className="dt-outline-module">
          <div>
            <header>
              <div className="dt-outline-module-head">
                <span>{t("Module {{n}}", { n: moduleIndex + 1 })}</span>
                {module.name.trim() !== topicName.trim() ? (
                  <h2>{module.name}</h2>
                ) : (
                  <span className="flex-1" />
                )}
                <span>
                  {module.mastered}/{module.total}
                </span>
              </div>
              {/* The ability this module delivers. A bare noun tells a learner
                  nothing about why these waypoints belong together, and this
                  sentence is also the contract the tutor may revise them
                  against — so it is worth the second line. */}
              {module.objective.trim() && (
                <p className="-mt-1 px-2.5 pb-1.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
                  {module.objective}
                </p>
              )}
            </header>
            <ul>
              {module.knowledge_points.map(point => {
                const selected = point.id === selectedId;
                const current = point.id === nextId;
                return (
                  <li key={point.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(selected ? null : point.id)}
                      aria-pressed={selected}
                      className="dt-panel-row"
                    >
                      <StatusMark point={point} />
                      <span
                        className={`min-w-0 flex-1 truncate text-[13px] ${
                          point.status === "new"
                            ? "text-[var(--muted-foreground)]"
                            : "text-[var(--foreground)]"
                        }`}
                      >
                        {point.name}
                      </span>
                      {current && (
                        <span className="shrink-0 rounded-full bg-[var(--primary)]/10 px-2 py-0.5 text-[10px] font-semibold text-[var(--primary)]">
                          {t("Next")}
                        </span>
                      )}
                      <span className="hidden shrink-0 text-[11px] text-[var(--muted-foreground)] sm:inline">
                        {statusLabel(point, t)}
                      </span>
                      <ChevronRight
                        className={`h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)] transition ${
                          selected ? "rotate-90" : ""
                        }`}
                      />
                    </button>
                    {selected && (
                      <ObjectiveDrawer
                        key={`${topic.path_id}:${point.id}`}
                        pathId={topic.path_id}
                        objectiveId={point.id}
                        revision={revision}
                        zh={zh}
                        onClose={() => onSelect(null)}
                        onOverride={onOverride}
                        onDefer={onDefer}
                        deferred={Boolean(point.deferred)}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      ))}
    </section>
  );
}

function ObjectiveDrawer({
  pathId,
  objectiveId,
  revision,
  zh,
  onClose,
  onOverride,
  onDefer,
  deferred,
}: {
  pathId: string;
  objectiveId: string;
  revision: number;
  zh: boolean;
  onClose: () => void;
  onOverride: (
    objectiveId: string,
    mastered: boolean,
    note: string,
  ) => Promise<void>;
  onDefer: (objectiveId: string, note: string) => Promise<void>;
  deferred: boolean;
}) {
  const { t } = useTranslation();
  const [report, setReport] = useState<ObjectiveReport | null>(null);
  const [confirmAction, setConfirmAction] = useState<
    "mastery" | "defer" | null
  >(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchObjectiveReport(pathId, objectiveId, { signal: controller.signal })
      .then(result => {
        if (!controller.signal.aborted) setReport(result);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(t("Evidence could not be loaded"));
      });
    return () => controller.abort();
  }, [objectiveId, pathId, revision, t]);

  const applyAction = async (action: "mastery" | "defer" | "restore") => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (action === "defer") {
        await onDefer(objectiveId, note);
      } else {
        await onOverride(objectiveId, action === "mastery", note);
      }
      setConfirmAction(null);
      setNote("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Update failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="dt-outline-drawer">
      {!report ? (
        <div className="flex min-h-32 items-center justify-center text-[var(--muted-foreground)]">
          {error ? error : <Loader2 className="h-5 w-5 animate-spin" />}
        </div>
      ) : (
        <>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                <span>{knowledgeTypeLabel(report.type, t)}</span>
                {report.mastery_source === "learner" && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-[var(--muted-foreground)]/10 px-2 py-0.5 text-[var(--muted-foreground)]">
                    <Sparkles className="h-3 w-3" />
                    {t("Confirmed by you")}
                  </span>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-2 py-1 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
            >
              {t("Collapse")}
            </button>
          </div>
          <ObjectiveDetail report={report} zh={zh} />

          {!report.assessed_mastered && (
            <div className="mt-5 pt-1">
              {report.mastery_source === "learner" ? (
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-xs leading-5 text-[var(--muted-foreground)]">
                    {t(
                      "Marked as known by you; assessed evidence is unchanged.",
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => void applyAction("restore")}
                    disabled={busy}
                    className="inline-flex h-9 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-xs font-medium hover:bg-[var(--accent)] disabled:opacity-50"
                  >
                    {busy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Undo2 className="h-3.5 w-3.5" />
                    )}
                    {t("Return to assessment")}
                  </button>
                </div>
              ) : confirmAction ? (
                <div>
                  <p className="mb-3 text-xs leading-5 text-[var(--muted-foreground)]">
                    {confirmAction === "mastery"
                      ? t(
                          "Confirming mastery counts toward progress and keeps the original assessment unchanged.",
                        )
                      : t(
                          "Skipping does not count as mastery. You can return to this knowledge point later.",
                        )}
                  </p>
                  <label className="text-xs font-medium text-[var(--foreground)]">
                    {t("Optional note")}
                    <textarea
                      autoFocus
                      value={note}
                      onChange={event => setNote(event.target.value)}
                      rows={2}
                      maxLength={500}
                      disabled={busy}
                      className="mt-2 w-full resize-none rounded-xl border border-[var(--input)] bg-[var(--background)] p-3 text-xs outline-none focus:border-[var(--ring)]"
                    />
                  </label>
                  <div className="mt-2 flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setConfirmAction(null);
                        setNote("");
                        setError(null);
                      }}
                      disabled={busy}
                      className="h-9 rounded-xl px-3 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
                    >
                      {t("Cancel")}
                    </button>
                    <button
                      type="button"
                      onClick={() => void applyAction(confirmAction)}
                      disabled={busy}
                      className="inline-flex h-9 items-center gap-2 rounded-xl bg-[var(--primary)] px-3 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-50"
                    >
                      {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                      {confirmAction === "mastery"
                        ? t("Confirm mastery")
                        : t("Skip for now")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmAction("mastery")}
                    className="inline-flex h-9 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-xs font-medium hover:bg-[var(--accent)]"
                  >
                    <LockKeyhole className="h-3.5 w-3.5" />
                    {t("I already know this — advance")}
                  </button>
                  {!deferred && (
                    <button
                      type="button"
                      onClick={() => setConfirmAction("defer")}
                      className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2 text-left text-xs font-medium hover:bg-[var(--accent)]"
                    >
                      <SkipForward className="h-3.5 w-3.5 shrink-0" />
                      {t("Skip this knowledge point for now")}
                    </button>
                  )}
                </div>
              )}
              {deferred && report.mastery_source !== "learner" && (
                <p className="mt-2 text-xs text-[var(--muted-foreground)]">
                  {t(
                    "Skipping does not count as mastery. You can return to this knowledge point later.",
                  )}
                </p>
              )}
              {error && (
                <p role="alert" className="mt-2 text-xs text-red-600">
                  {error}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </aside>
  );
}

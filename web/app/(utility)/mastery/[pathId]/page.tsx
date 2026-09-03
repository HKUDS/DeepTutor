"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Compass,
  Loader2,
  MoreHorizontal,
  PencilRuler,
  Radio,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";

import { ModuleOutline } from "@/components/space/learning/ModuleOutline";
import { ConfirmDialog } from "@/components/space/learning/ConfirmDialog";
import { EditTopicRouteDialog } from "@/components/space/learning/EditTopicRouteDialog";
import {
  topicDisplayName,
  type Translate,
} from "@/components/space/learning/format";
import { PathTitle } from "@/components/space/learning/PathTitle";
import { ReviewTrail } from "@/components/space/learning/ReviewTrail";
import { SessionCamp } from "@/components/space/learning/SessionCamp";
import { useMasteryPathActivity } from "@/hooks/useMasteryPathActivity";
import {
  deleteProgress,
  fetchMasteryTopic,
  fetchMasteryTopicSessions,
  redoProgress,
  renameProgress,
  setMasteryObjectiveOverride,
  type MasteryTopic,
  type TopicSession,
} from "@/lib/learning-api";

const NEXT_LABELS: Record<string, { zh: string; en: string }> = {
  probe: {
    zh: "先用一道探查题看看你是否已经掌握",
    en: "Start with a probe and test out if you already know it",
  },
  practice: {
    zh: "继续练习，直到稳定越过掌握门槛",
    en: "Practice until you reliably clear the mastery gate",
  },
  assess: {
    zh: "用自己的话讲清楚这个概念",
    en: "Explain this clearly in your own words",
  },
  review: { zh: "复习这个记忆信标", en: "Revisit this memory beacon" },
  answer_pending: {
    zh: "完成导师正在等待的回答",
    en: "Complete the answer your tutor is waiting for",
  },
  complete: {
    zh: "整片疆域已经点亮",
    en: "The whole territory is illuminated",
  },
};

const NEXT_CTA_LABELS: Record<string, { zh: string; en: string }> = {
  review: { zh: "开始本次复习", en: "Start this review" },
  answer_pending: {
    zh: "回到原会话作答",
    en: "Answer in the original session",
  },
  complete: { zh: "继续自由探索", en: "Keep exploring" },
};

export default function MasteryTopicPage() {
  const params = useParams<{ pathId: string }>();
  const pathId = String(params.pathId || "");
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const zh = Boolean(i18n.language?.toLowerCase().startsWith("zh"));
  const [topic, setTopic] = useState<MasteryTopic | null>(null);
  const [sessions, setSessions] = useState<TopicSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<"reset" | "delete" | null>(
    null,
  );
  const [mutationBusy, setMutationBusy] = useState(false);
  const editorTriggerRef = useRef<HTMLElement | null>(null);
  const confirmTriggerRef = useRef<HTMLElement | null>(null);
  const activity = useMasteryPathActivity(pathId || null);

  const openEditor = (trigger: HTMLButtonElement) => {
    editorTriggerRef.current = trigger;
    setEditorOpen(true);
  };

  const openConfirmation = (
    action: "reset" | "delete",
    trigger: HTMLButtonElement,
  ) => {
    confirmTriggerRef.current = trigger;
    setConfirmAction(action);
  };

  const loadTopic = useCallback(async () => {
    try {
      const next = await fetchMasteryTopic(pathId, { cache: "no-store" });
      setTopic(next);
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("The map could not be loaded"),
      );
    } finally {
      setLoading(false);
    }
  }, [pathId, t]);

  const loadSessions = useCallback(async () => {
    try {
      setSessions(
        await fetchMasteryTopicSessions(pathId, { cache: "no-store" }),
      );
      setSessionsError(false);
    } catch {
      // Keep whatever we last showed. Blanking the list turns a network blip
      // into "you have no sessions", which is a different and alarming claim.
      setSessionsError(true);
    } finally {
      setSessionsLoading(false);
    }
  }, [pathId]);

  useEffect(() => {
    void loadTopic();
  }, [activity.revision, loadTopic]);

  useEffect(() => {
    void loadSessions();
  }, [activity.revision, activity.signal, loadSessions]);

  useEffect(() => {
    if (!selectedId || !topic) return;
    const stillThere = topic.map.modules.some((module) =>
      module.knowledge_points.some((point) => point.id === selectedId),
    );
    if (!stillThere) setSelectedId(null);
  }, [selectedId, topic]);

  const sourceLabels = useMemo(
    () =>
      topic?.sources.filter((source) => source.kind !== "goal").slice(0, 5) ??
      [],
    [topic],
  );
  const displayName = topic ? topicDisplayName(topic, t) : "";

  const refresh = async () => {
    await Promise.all([loadTopic(), loadSessions()]);
    activity.refresh();
  };

  const handleOverride = async (
    objectiveId: string,
    mastered: boolean,
    note: string,
  ) => {
    const result = await setMasteryObjectiveOverride(
      pathId,
      objectiveId,
      mastered,
      note,
    );
    setTopic((previous) =>
      previous
        ? { ...previous, map: result.map, path_revision: result.path_revision }
        : previous,
    );
    await loadTopic();
  };

  /**
   * The rest of this page rediscovers changes through the activity feed's
   * revision counter, which lands a poll interval later. Waiting that long to
   * see the edit you just made reads as a failed save, so the new name is
   * applied locally the moment the write returns.
   */
  const handleRename = async (name: string) => {
    const saved = await renameProgress(pathId, name);
    setTopic((previous) =>
      previous ? { ...previous, name: saved.name } : previous,
    );
    activity.refresh();
  };

  const handleReset = async () => {
    setMutationBusy(true);
    try {
      await redoProgress(pathId);
      setSelectedId(null);
      await refresh();
      setConfirmAction(null);
    } finally {
      setMutationBusy(false);
    }
  };

  const handleDelete = async () => {
    setMutationBusy(true);
    try {
      await deleteProgress(pathId);
      router.replace("/mastery");
    } finally {
      setMutationBusy(false);
    }
  };

  if (loading && !topic) {
    return (
      <div className="mastery-shell flex h-full items-center justify-center text-[var(--muted-foreground)]">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  if (!topic) {
    return (
      <div className="mastery-shell flex h-full flex-col items-center justify-center px-6 text-center">
        <Compass className="h-10 w-10 text-[var(--muted-foreground)] opacity-40" />
        <h1 className="mt-4 text-lg font-semibold">
          {t("This map could not be found")}
        </h1>
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">{error}</p>
        <Link
          href="/mastery"
          className="mt-5 text-sm font-medium text-[var(--primary)] hover:underline"
        >
          {t("Back to topics")}
        </Link>
      </div>
    );
  }

  const nextCopy = NEXT_LABELS[topic.next.action] ?? {
    zh: topic.next.reason,
    en: topic.next.reason,
  };
  const progress = topic.map.counts.total
    ? Math.round((topic.map.counts.mastered / topic.map.counts.total) * 100)
    : 0;
  const needsRouteRepair = topic.map.counts.total === 0;
  const nextCta = NEXT_CTA_LABELS[topic.next.action];
  const pendingSessionId =
    topic.next.session_id ||
    sessions.find((session) => session.has_pending_question)?.session_id;
  const continuationSessionId =
    topic.next.action === "answer_pending"
      ? pendingSessionId
      : sessions[0]?.session_id;

  return (
    <main className="mastery-shell h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[1180px] px-4 pb-40 pt-6 sm:px-7 sm:pb-10 lg:px-8 lg:py-8">
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/mastery"
            className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t("Learning topics")}
          </Link>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={(event) => openEditor(event.currentTarget)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 text-[12px] font-medium text-[var(--muted-foreground)] transition hover:text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40"
            >
              <PencilRuler className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">{t("Edit modules")}</span>
            </button>
            <details className="relative">
              <summary className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] transition hover:text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40">
                <MoreHorizontal className="h-4 w-4" />
                <span className="sr-only">{t("More actions")}</span>
              </summary>
              <div className="absolute right-0 z-20 mt-2 w-44 rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1.5 text-xs shadow-xl">
                <button
                  type="button"
                  onClick={(event) =>
                    openConfirmation("reset", event.currentTarget)
                  }
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-[var(--accent)]"
                >
                  <RotateCcw className="h-3.5 w-3.5" /> {t("Reset progress")}
                </button>
                <button
                  type="button"
                  onClick={(event) =>
                    openConfirmation("delete", event.currentTarget)
                  }
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-red-600 hover:bg-red-500/10"
                >
                  <Trash2 className="h-3.5 w-3.5" /> {t("Delete topic")}
                </button>
              </div>
            </details>
          </div>
        </div>

        <header className="mt-6 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <div className="min-w-0">
                <PathTitle
                  displayName={displayName}
                  storedName={topic.name}
                  onRename={handleRename}
                />
                <p className="mt-1 max-w-3xl text-sm text-[var(--muted-foreground)]">
                  {topic.metadata.description || topic.metadata.goal}
                </p>
              </div>
            </div>
            {sourceLabels.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2 pl-0 sm:pl-[60px]">
                {sourceLabels.map((source) => (
                  <span
                    key={source.id}
                    className="inline-flex items-center gap-1.5 rounded-full bg-[var(--muted)] px-2.5 py-1 text-[10px] text-[var(--muted-foreground)]"
                  >
                    <BookOpen className="h-3 w-3" /> {source.label}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className="text-[13px] tabular-nums text-[var(--muted-foreground)]">
              {topic.map.counts.mastered}/{topic.map.counts.total}{" "}
              {t("knowledge points")}
            </span>
            <span className="h-3 w-px bg-[var(--border)]" aria-hidden="true" />
            <div className="flex items-center gap-2">
              <div className="h-1 w-24 overflow-hidden rounded-full bg-[var(--muted)]">
                <div
                  className="h-full rounded-full bg-[var(--primary)] transition-[width] duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="text-[13px] font-medium tabular-nums text-[var(--foreground)]">
                {progress}%
              </span>
            </div>
          </div>
        </header>

        <section className="fixed bottom-3 left-4 right-4 z-20 flex flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)]/95 p-4 backdrop-blur sm:static sm:mt-6 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:rounded-none sm:border-0 sm:border-y sm:border-[var(--border)] sm:bg-transparent sm:px-0 sm:py-4 sm:backdrop-blur-none">
          <div className="flex min-w-0 items-baseline gap-3">
            <span className="shrink-0 text-[12px] text-[var(--muted-foreground)]">
              {t("Next up")}
            </span>
            <div className="min-w-0">
              <div className="truncate text-[14px] font-medium text-[var(--foreground)]">
                {needsRouteRepair
                  ? t("Outline is empty")
                  : topic.next.knowledge_point_name ||
                    t("Celebrate completion")}
              </div>
              <p className="mt-0.5 truncate text-[12px] text-[var(--muted-foreground)]">
                {needsRouteRepair
                  ? t(
                      "This migrated topic has no modules yet. Add at least one module and knowledge point to begin.",
                    )
                  : zh
                    ? nextCopy.zh
                    : nextCopy.en}
              </p>
            </div>
          </div>
          {needsRouteRepair ? (
            <button
              type="button"
              onClick={(event) => openEditor(event.currentTarget)}
              className="inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[13px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
            >
              <PencilRuler className="h-4 w-4" />
              {t("Add modules")}
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          ) : (
            <Link
              href={
                continuationSessionId
                  ? `/mastery/${encodeURIComponent(pathId)}/sessions/${encodeURIComponent(continuationSessionId)}`
                  : `/mastery/${encodeURIComponent(pathId)}/sessions`
              }
              className="inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[13px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
            >
              {nextCta
                ? zh
                  ? nextCta.zh
                  : nextCta.en
                : topic.session_count > 0
                  ? t("Continue learning")
                  : t("Begin first waypoint")}
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          )}
        </section>

        <div className="mt-6 grid items-start gap-7 lg:grid-cols-[minmax(0,1fr)_312px]">
          {needsRouteRepair ? (
            <section className="mastery-map-paper flex min-h-72 flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] p-8 text-center">
              <PencilRuler className="h-9 w-9 text-[var(--mastery-route)]" />
              <h2 className="mt-4 text-lg font-semibold">
                {t("Add the missing modules")}
              </h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-[var(--muted-foreground)]">
                {t(
                  "The topic migrated safely but has no modules yet. Define the abilities you want to master before tutoring begins.",
                )}
              </p>
              <button
                type="button"
                onClick={(event) => openEditor(event.currentTarget)}
                className="mt-5 inline-flex h-10 items-center gap-2 rounded-xl bg-[var(--mastery-ink)] px-4 text-sm font-medium text-[var(--mastery-paper-raised)]"
              >
                <PencilRuler className="h-4 w-4" />
                {t("Add modules and knowledge points")}
              </button>
            </section>
          ) : (
            <div className="space-y-5">
              <ModuleOutline
                topic={topic}
                revision={Math.max(topic.path_revision, activity.revision)}
                selectedId={selectedId}
                zh={zh}
                onSelect={setSelectedId}
                onOverride={handleOverride}
              />
              <ReviewTrail
                reviews={topic.reviews}
                zh={zh}
                onSelect={(objectiveId) => {
                  setSelectedId(objectiveId);
                  document
                    .getElementById("mastery-outline-start")
                    ?.scrollIntoView({
                      behavior: window.matchMedia(
                        "(prefers-reduced-motion: reduce)",
                      ).matches
                        ? "auto"
                        : "smooth",
                    });
                }}
              />
            </div>
          )}
          <div className="space-y-5 lg:sticky lg:top-6">
            <SessionCamp
              pathId={pathId}
              sessions={sessions}
              loading={sessionsLoading}
              stale={sessionsError}
              onRetry={() => void loadSessions()}
              zh={zh}
            />
          </div>
        </div>
      </div>
      {editorOpen && (
        <EditTopicRouteDialog
          topic={topic}
          returnFocusRef={editorTriggerRef}
          onClose={() => setEditorOpen(false)}
          onSaved={(next) => {
            setTopic(next);
            setSelectedId(null);
            setEditorOpen(false);
            activity.refresh();
          }}
        />
      )}
      {confirmAction === "reset" && (
        <ConfirmDialog
          title={t("Reset learning progress?")}
          description={t(
            "Modules and knowledge points stay. Mastery evidence, pending questions, and review schedules will be cleared.",
          )}
          confirmLabel={t("Confirm reset")}
          cancelLabel={t("Cancel")}
          busy={mutationBusy}
          returnFocusRef={confirmTriggerRef}
          onConfirm={() => void handleReset()}
          onClose={() => setConfirmAction(null)}
        />
      )}
      {confirmAction === "delete" && (
        <ConfirmDialog
          title={t("Permanently delete this topic?")}
          description={t(
            "The map, evidence, review schedule, and linked records will be deleted. This cannot be undone.",
          )}
          confirmLabel={t("Delete permanently")}
          cancelLabel={t("Cancel")}
          destructive
          busy={mutationBusy}
          returnFocusRef={confirmTriggerRef}
          onConfirm={() => void handleDelete()}
          onClose={() => setConfirmAction(null)}
        />
      )}
    </main>
  );
}

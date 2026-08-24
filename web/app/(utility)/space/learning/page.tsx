"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  GraduationCap,
  Loader2,
  RotateCcw,
  Trash2,
  MessageSquare,
} from "lucide-react";

import {
  fetchAllProgress,
  fetchMasteryMap,
  deleteProgress,
  redoProgress,
  skipPendingQuestion,
  type ProgressSummary,
  type MasteryMapResult,
} from "@/lib/learning-api";
import { newMasteryPathChatUrl } from "@/lib/chat-launch-intent";
import { useMasteryPathActivity } from "@/hooks/useMasteryPathActivity";
import { ActivityTimeline } from "@/components/space/learning/ActivityTimeline";
import { PathMap } from "@/components/space/learning/PathMap";
import { formatRelative } from "@/components/space/learning/format";

/**
 * Mastery Path dashboard — the persistent "screen" of the mastery experience.
 *
 * The tutoring itself runs on the chat agent loop (pick "Mastery Path" mode in
 * Chat); this page is the map of where the learner stands, and it follows
 * along live: the engine's event feed is polled for anything past the revision
 * already on screen, and every read here re-runs when the path moves. So a
 * learner can keep this open beside a tutoring conversation and watch the gate
 * clear. "Continue" starts a focused chat while retaining the selected path.
 */
export default function MasteryPathPage() {
  const { i18n } = useTranslation();
  const zh = !!i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
  const router = useRouter();

  const [paths, setPaths] = useState<ProgressSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<MasteryMapResult | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [tab, setTab] = useState<"map" | "activity">("map");

  const { events, revision, refresh } = useMasteryPathActivity(selected);

  const loadList = useCallback(async () => {
    try {
      const result = await fetchAllProgress();
      const withContent = result.summaries
        .filter((s) => s.kp_count > 0)
        .sort((a, b) => b.updated_at - a.updated_at);
      setPaths(withContent);
      setSelected((prev) => prev ?? withContent[0]?.book_id ?? null);
    } catch {
      setPaths([]);
    } finally {
      setLoadingList(false);
    }
  }, []);

  /* The list carries per-path mastery, so it is as live as the map. */
  useEffect(() => {
    void loadList();
  }, [loadList, revision]);

  /* Re-read the map whenever the path advances — `revision` is that signal. */
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setLoadingDetail(
      (wasLoading) => wasLoading || detail?.book_id !== selected,
    );
    fetchMasteryMap(selected, { signal: controller.signal })
      .then(setDetail)
      .catch(() => {
        if (!controller.signal.aborted) setDetail(null);
      })
      .finally(() => setLoadingDetail(false));
    return () => controller.abort();
    // `detail` is read only to decide whether to show a spinner; depending on
    // it would refetch the map every time the map arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, revision]);

  /* Objective id → name, so the activity feed reads in the learner's terms. */
  const objectiveNames = useMemo(() => {
    const names: Record<string, string> = {};
    for (const group of detail?.map.modules ?? [])
      for (const kp of group.knowledge_points) names[kp.id] = kp.name;
    return names;
  }, [detail]);

  /* Mutations refresh through the same path as the tutor's own changes. */
  const afterMutation = useCallback(async () => {
    await loadList();
    refresh();
  }, [loadList, refresh]);

  const handleDelete = useCallback(
    async (pathId: string) => {
      if (
        !window.confirm(
          tr("确定删除这条精通之路？", "Delete this mastery path?"),
        )
      )
        return;
      await deleteProgress(pathId);
      setSelected(null);
      await afterMutation();
    },
    [afterMutation, tr],
  );

  const handleRedo = useCallback(
    async (pathId: string) => {
      if (
        !window.confirm(
          tr(
            "重置进度？知识点保留，但掌握度与复习计划清空。",
            "Reset progress? Objectives are kept, but mastery and reviews are cleared.",
          ),
        )
      )
        return;
      await redoProgress(pathId);
      await afterMutation();
    },
    [afterMutation, tr],
  );

  const handleSkipQuestion = useCallback(
    async (pathId: string) => {
      if (
        !window.confirm(
          tr(
            "跳过这道待回答的题目？已掌握的进度都会保留。",
            "Skip the question awaiting an answer? Mastery already earned is kept.",
          ),
        )
      )
        return;
      await skipPendingQuestion(pathId);
      await afterMutation();
    },
    [afterMutation, tr],
  );

  return (
    <div className="flex h-full">
      {/* Path list */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-[var(--border)]">
        <header className="border-b border-[var(--border)] px-4 py-3">
          <div className="flex items-center gap-2 text-[var(--foreground)]">
            <GraduationCap className="h-4 w-4" />
            <h1 className="text-sm font-semibold">
              {tr("精通之路", "Mastery Path")}
            </h1>
          </div>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {tr(
              "掌握式学习：硬门槛 + 间隔复习",
              "Mastery-based learning: hard gate + spaced review",
            )}
          </p>
        </header>
        <div className="flex-1 space-y-1 overflow-y-auto p-2">
          {loadingList ? (
            <div className="flex items-center justify-center py-8 text-[var(--muted-foreground)]">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : paths.length === 0 ? (
            <p className="px-2 py-3 text-xs leading-relaxed text-[var(--muted-foreground)]">
              {tr(
                "还没有精通之路。去「对话」选择 Mastery Path 模式，让导师根据你的材料建一条。",
                "No paths yet. Open Chat, pick Mastery Path mode, and ask the tutor to build one from your materials.",
              )}
            </p>
          ) : (
            paths.map((path) => (
              <button
                key={path.book_id}
                onClick={() => setSelected(path.book_id)}
                className={`w-full cursor-pointer rounded-md px-3 py-2 text-left transition-colors ${
                  selected === path.book_id
                    ? "bg-[var(--primary)]/10 ring-1 ring-[var(--primary)]/30"
                    : "hover:bg-[var(--accent)]"
                }`}
              >
                <div className="truncate text-sm text-[var(--foreground)]">
                  {path.name}
                </div>
                <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                  {path.kp_count} {tr("个知识点", "objectives")} ·{" "}
                  {path.avg_mastery_pct}%
                </div>
              </button>
            ))
          )}
        </div>
        <footer className="border-t border-[var(--border)] p-2">
          <button
            onClick={() => router.push("/home")}
            className="flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            {tr("新建（在对话中）", "New (in Chat)")}
          </button>
        </footer>
      </aside>

      {/* Selected path */}
      <section className="flex-1 overflow-y-auto">
        {loadingDetail && !detail ? (
          <div className="flex h-full items-center justify-center text-[var(--muted-foreground)]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : !detail || !selected ? (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center text-[var(--muted-foreground)]">
            <GraduationCap className="mb-3 h-10 w-10 opacity-40" />
            <p className="max-w-sm text-sm leading-relaxed">
              {tr(
                "选择一条精通之路查看进度地图，或在「对话」里用 Mastery Path 模式开始。",
                "Select a path to see its progress map, or start one in Chat with Mastery Path mode.",
              )}
            </p>
          </div>
        ) : (
          <PathView
            pathId={selected}
            result={detail}
            revision={revision}
            events={events}
            objectiveNames={objectiveNames}
            tab={tab}
            onTabChange={setTab}
            zh={zh}
            tr={tr}
            onContinue={() => router.push(newMasteryPathChatUrl(selected))}
            onSkipQuestion={() => handleSkipQuestion(selected)}
            onRedo={() => handleRedo(selected)}
            onDelete={() => handleDelete(selected)}
          />
        )}
      </section>
    </div>
  );
}

const ACTION_LABEL: Record<string, { cn: string; en: string }> = {
  probe: { cn: "先探查是否已掌握", en: "Probe — test out first" },
  practice: { cn: "练习直到达标", en: "Practice until the gate clears" },
  assess: { cn: "用自己的话解释", en: "Explain it in your own words" },
  review: { cn: "到期复习", en: "Due for review" },
  answer_pending: {
    cn: "有待回答的问题",
    en: "A question is awaiting your answer",
  },
  complete: { cn: "已全部掌握 🎉", en: "All mastered 🎉" },
};

function PathView({
  pathId,
  result,
  revision,
  events,
  objectiveNames,
  tab,
  onTabChange,
  zh,
  tr,
  onContinue,
  onSkipQuestion,
  onRedo,
  onDelete,
}: {
  pathId: string;
  result: MasteryMapResult;
  revision: number;
  events: React.ComponentProps<typeof ActivityTimeline>["events"];
  objectiveNames: Record<string, string>;
  tab: "map" | "activity";
  onTabChange: (tab: "map" | "activity") => void;
  zh: boolean;
  tr: (cn: string, en: string) => string;
  onContinue: () => void;
  onSkipQuestion: () => void;
  onRedo: () => void;
  onDelete: () => void;
}) {
  const { map, next } = result;
  const pct = map.counts.total
    ? Math.round((map.counts.mastered / map.counts.total) * 100)
    : 0;
  const action = ACTION_LABEL[next.action] ?? {
    cn: next.reason,
    en: next.reason,
  };
  const lastEvent = events.length ? events[events.length - 1] : null;

  return (
    <div className="mx-auto max-w-2xl px-6 py-5">
      {/* Header: progress + actions */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <span>
              {map.counts.mastered}/{map.counts.total}{" "}
              {tr("已掌握", "mastered")}
            </span>
            {map.due_reviews > 0 && (
              <span className="text-yellow-600">
                · {map.due_reviews} {tr("项待复习", "due for review")}
              </span>
            )}
            {lastEvent && (
              <span>
                · {tr("最近更新 ", "updated ")}
                {formatRelative(lastEvent.created_at, zh)}
              </span>
            )}
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-[var(--accent)]">
            <div
              className="h-full bg-green-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            onClick={onRedo}
            title={tr("重置进度", "Reset progress")}
            className="cursor-pointer rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
          <button
            onClick={onDelete}
            title={tr("删除", "Delete")}
            className="cursor-pointer rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-500"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Next step */}
      <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
        <div className="text-xs text-[var(--muted-foreground)]">
          {tr("接下来", "Next")}
        </div>
        <div className="mt-0.5 text-sm font-medium text-[var(--foreground)]">
          {next.action === "complete"
            ? tr(action.cn, action.en)
            : `${next.knowledge_point_name} — ${tr(action.cn, action.en)}`}
        </div>
        {next.pending_prompt && (
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {next.pending_prompt}
          </p>
        )}
        <div className="mt-1.5 flex items-center gap-3">
          <button
            onClick={onContinue}
            className="cursor-pointer text-xs text-[var(--primary)] hover:underline"
          >
            {tr("在对话中继续辅导 →", "Continue tutoring in Chat →")}
          </button>
          {/* Only reachable escape from a question whose conversation is gone;
              unlike Reset it keeps every mastery level already earned. */}
          {next.action === "answer_pending" && (
            <button
              onClick={onSkipQuestion}
              className="cursor-pointer text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline"
            >
              {tr("跳过这道题", "Skip this question")}
            </button>
          )}
        </div>
      </div>

      {/* Map / activity */}
      <div className="mt-5 flex items-center gap-4 border-b border-[var(--border)]">
        {(
          [
            ["map", tr("地图", "Map")],
            ["activity", tr("活动", "Activity")],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            onClick={() => onTabChange(value)}
            className={`-mb-px cursor-pointer border-b-2 pb-1.5 text-xs transition-colors ${
              tab === value
                ? "border-[var(--primary)] text-[var(--foreground)]"
                : "border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {label}
            {value === "activity" && events.length > 0 && (
              <span className="ml-1 text-[var(--muted-foreground)]">
                {events.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {tab === "map" ? (
          /* Keyed by path: switching paths must drop whichever objective was
             open, since its id belongs to the path that is going away. */
          <PathMap
            key={pathId}
            pathId={pathId}
            map={map}
            revision={revision}
            tr={tr}
            zh={zh}
          />
        ) : (
          <ActivityTimeline
            events={events}
            objectiveNames={objectiveNames}
            tr={tr}
            zh={zh}
          />
        )}
      </div>
    </div>
  );
}

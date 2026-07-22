"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  GraduationCap,
  Loader2,
  RotateCcw,
  Trash2,
  CircleCheck,
  CircleDot,
  Circle,
  MessageSquare,
} from "lucide-react";

import {
  fetchAllProgress,
  fetchMasteryMap,
  deleteProgress,
  redoProgress,
  type ProgressSummary,
  type MasteryMapResult,
  type ObjectiveStatus,
} from "@/lib/learning-api";

/**
 * Mastery Path dashboard — the persistent "screen" of the mastery experience.
 *
 * The tutoring itself runs on the chat agent loop (pick "Mastery Path" mode in
 * Chat); this page is the map of where the learner stands. It reads the
 * gate-accurate snapshot from ``/progress/{id}/map`` (per-type status computed
 * by ``deeptutor.learning.policy``) so the colours here agree with the gate the
 * tutor enforces. A path is keyed by its chat session, so "Continue" reopens
 * that session in mastery mode.
 */
export default function MasteryPathPage() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
  const router = useRouter();

  const [paths, setPaths] = useState<ProgressSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<MasteryMapResult | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const loadList = useCallback(async () => {
    setLoadingList(true);
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

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    fetchMasteryMap(selected)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const handleDelete = useCallback(
    async (pathId: string) => {
      if (
        !window.confirm(
          tr("确定删除这条精通之路？", "Delete this mastery path?"),
        )
      )
        return;
      await deleteProgress(pathId);
      if (selected === pathId) setSelected(null);
      await loadList();
    },
    [selected, loadList, tr],
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
      const result = await fetchMasteryMap(pathId);
      setDetail(result);
    },
    [tr],
  );

  return (
    <div className="flex h-full">
      {/* Path list */}
      <aside className="w-64 shrink-0 border-r border-[var(--border)] flex flex-col">
        <header className="px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2 text-[var(--foreground)]">
            <GraduationCap className="w-4 h-4" />
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
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loadingList ? (
            <div className="flex items-center justify-center py-8 text-[var(--muted-foreground)]">
              <Loader2 className="w-4 h-4 animate-spin" />
            </div>
          ) : paths.length === 0 ? (
            <p className="px-2 py-3 text-xs text-[var(--muted-foreground)] leading-relaxed">
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
                className={`w-full text-left px-3 py-2 rounded-md transition-colors cursor-pointer ${
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
        <footer className="p-2 border-t border-[var(--border)]">
          <button
            onClick={() => router.push("/home")}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90 transition-opacity cursor-pointer"
          >
            <MessageSquare className="w-3.5 h-3.5" />
            {tr("新建（在对话中）", "New (in Chat)")}
          </button>
        </footer>
      </aside>

      {/* Selected path map */}
      <section className="flex-1 overflow-y-auto">
        {loadingDetail ? (
          <div className="flex items-center justify-center h-full text-[var(--muted-foreground)]">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        ) : !detail ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 text-[var(--muted-foreground)]">
            <GraduationCap className="w-10 h-10 mb-3 opacity-40" />
            <p className="text-sm max-w-sm leading-relaxed">
              {tr(
                "选择一条精通之路查看进度地图，或在「对话」里用 Mastery Path 模式开始。",
                "Select a path to see its progress map, or start one in Chat with Mastery Path mode.",
              )}
            </p>
          </div>
        ) : (
          <MapView
            result={detail}
            zh={!!zh}
            tr={tr}
            onContinue={() =>
              selected && router.push(`/home/${encodeURIComponent(selected)}`)
            }
            onRedo={() => selected && handleRedo(selected)}
            onDelete={() => selected && handleDelete(selected)}
          />
        )}
      </section>
    </div>
  );
}

const STATUS_META: Record<
  ObjectiveStatus,
  { cn: string; en: string; className: string }
> = {
  mastered: { cn: "已掌握", en: "Mastered", className: "text-green-500" },
  learning: { cn: "学习中", en: "Learning", className: "text-yellow-500" },
  new: {
    cn: "未开始",
    en: "Not started",
    className: "text-[var(--muted-foreground)]",
  },
};

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

function StatusIcon({ status }: { status: ObjectiveStatus }) {
  const cls = `w-3 h-3 shrink-0 ${STATUS_META[status].className}`;
  if (status === "mastered") return <CircleCheck className={cls} />;
  if (status === "learning") return <CircleDot className={cls} />;
  return <Circle className={cls} />;
}

function MapView({
  result,
  zh,
  tr,
  onContinue,
  onRedo,
  onDelete,
}: {
  result: MasteryMapResult;
  zh: boolean;
  tr: (cn: string, en: string) => string;
  onContinue: () => void;
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

  return (
    <div className="max-w-2xl mx-auto px-6 py-5">
      {/* Header: progress + next + actions */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
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
          </div>
          <div className="mt-1.5 h-1.5 w-full rounded-full bg-[var(--accent)] overflow-hidden">
            <div
              className="h-full bg-green-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={onRedo}
            title={tr("重置进度", "Reset progress")}
            className="p-1.5 rounded-md text-[var(--muted-foreground)] hover:bg-[var(--accent)] cursor-pointer"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
          <button
            onClick={onDelete}
            title={tr("删除", "Delete")}
            className="p-1.5 rounded-md text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-500 cursor-pointer"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Next step */}
      <button
        onClick={onContinue}
        className="mt-4 w-full text-left rounded-lg border border-[var(--border)] hover:border-[var(--primary)]/40 hover:bg-[var(--accent)] p-3 transition-colors cursor-pointer"
      >
        <div className="text-xs text-[var(--muted-foreground)]">
          {tr("接下来", "Next")}
        </div>
        <div className="mt-0.5 text-sm font-medium text-[var(--foreground)]">
          {next.action === "complete"
            ? tr(action.cn, action.en)
            : `${next.knowledge_point_name} — ${tr(action.cn, action.en)}`}
        </div>
        <div className="mt-1 text-xs text-[var(--primary)]">
          {tr("在对话中继续辅导 →", "Continue tutoring in Chat →")}
        </div>
      </button>

      {/* Module / objective map */}
      <div className="mt-5 space-y-4">
        {map.modules.map((module) => (
          <div key={module.id}>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-[var(--foreground)]">
                {module.name}
              </h3>
              <span className="text-xs text-[var(--muted-foreground)]">
                {module.mastered}/{module.total}
              </span>
            </div>
            <div className="mt-1.5 space-y-1">
              {module.knowledge_points.map((kp) => (
                <div
                  key={kp.id}
                  className="flex items-center gap-2 px-2 py-1 rounded-md text-sm"
                >
                  <StatusIcon status={kp.status} />
                  <span className="flex-1 truncate text-[var(--foreground)]">
                    {kp.name}
                  </span>
                  <span className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                    {kp.type}
                  </span>
                  <span
                    className={`text-xs ${STATUS_META[kp.status].className}`}
                  >
                    {zh ? STATUS_META[kp.status].cn : STATUS_META[kp.status].en}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

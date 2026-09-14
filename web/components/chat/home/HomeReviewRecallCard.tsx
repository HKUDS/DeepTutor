"use client";

/**
 * Home review recall card (student retention).
 *
 * Two-tier recall so every returning student gets a hook, not just those with
 * mastery paths:
 *  - Tier 1: mastery paths with due reviews ("N items due today") — students
 *    already inside the learning loop.
 *  - Tier 2 (fallback): un-attributed wrong notebook entries ("N 道错题还没
 *    归因") — covers solve/quiz-only students who never built a path.
 *
 * Renders nothing when both tiers come back empty (fresh accounts keep the
 * plain greeting). Path map fetches run in parallel.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { fetchAllProgress, fetchMasteryMap } from "@/lib/learning-api";
import { listNotebookEntries } from "@/lib/notebook-api";

interface RecallState {
  dueTotal: number;
  wrongCount: number;
  primaryTitle: string;
  otherCount: number;
}

export default function HomeReviewRecallCard() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const [state, setState] = useState<RecallState | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [active, wrong] = await Promise.all([
          fetchAllProgress()
            .then((r) =>
              (r.summaries || [])
                .filter((s) => s.kp_count > 0)
                .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0)),
            )
            .catch(() => [] as { book_id: string; name: string; updated_at?: number }[]),
          listNotebookEntries({ is_correct: false, limit: 1 })
            .then((r) => r?.total ?? 0)
            .catch(() => 0),
        ]);
        if (cancelled) return;
        if (!active.length && !wrong) return;

        let dueTotal = 0;
        await Promise.all(
          active.slice(0, 3).map(async (s) => {
            try {
              const { map } = await fetchMasteryMap(s.book_id);
              dueTotal += map?.due_reviews || 0;
            } catch {
              /* one path failing must not blank the card */
            }
          }),
        );
        if (cancelled) return;
        setState({
          dueTotal,
          wrongCount: wrong,
          primaryTitle: active[0]?.name || active[0]?.book_id || "",
          otherCount: Math.max(0, active.length - 1),
        });
      } catch {
        /* not signed in / API unavailable → stay hidden */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!state) return null;

  const hasDue = state.dueTotal > 0;
  const hasWrong = !hasDue && state.wrongCount > 0;
  const headline = hasDue
    ? zh
      ? `今日有 ${state.dueTotal} 项复习到期`
      : `${state.dueTotal} item${state.dueTotal > 1 ? "s" : ""} due for review today`
    : hasWrong
      ? zh
        ? `你有 ${state.wrongCount} 道错题还没归因`
        : `${state.wrongCount} wrong item${state.wrongCount > 1 ? "s" : ""} not yet traced`
      : zh
        ? "继续上次的学习"
        : "Continue where you left off";
  const sub = hasWrong
    ? zh
      ? "错题归因，找到失分根源"
      : "Trace them to find where points leak"
    : state.otherCount
      ? `${state.primaryTitle} ${zh ? `等 ${state.otherCount + 1} 本在学` : `+ ${state.otherCount} more paths`}`
      : state.primaryTitle;
  const target = hasWrong ? "notebook" : "space/learning";
  const href = `/${target}`;

  return (
    <div className="mb-6 w-full max-w-[960px]">
      <Link
        href={href}
        className="group flex w-full items-center justify-between gap-4 rounded-xl border border-[var(--border)] bg-[var(--card)] px-5 py-4 transition-colors hover:border-teal-500/40"
      >
        <div className="min-w-0">
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {headline}
          </p>
          <p className="mt-0.5 truncate text-[12px] text-[var(--muted-foreground)]">
            {sub}
          </p>
        </div>
        <span className="shrink-0 rounded-lg bg-teal-500/10 px-3 py-1.5 text-[13px] font-medium text-teal-600 dark:text-teal-400">
          {zh ? (hasDue ? "去复习" : hasWrong ? "去归因" : "继续学习") : hasDue ? "Review now" : hasWrong ? "Trace now" : "Resume"}
          <span className="ml-1 inline-block transition-transform group-hover:translate-x-0.5">→</span>
        </span>
      </Link>
    </div>
  );
}

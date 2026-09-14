"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { BookOpen, Compass, GraduationCap, PlayCircle } from "lucide-react";

import {
  getDailyPlan,
  type ContinueKind,
  type DailyPlan,
  type KpRecommendation,
} from "@/lib/daily-plan-api";

/**
 * The "today" card at the top of the learning space: pick up where the
 * learner left off, plus the one-to-three weakest knowledge points the
 * mastery store has evidence for.
 *
 * Every state degrades quietly: loading is a skeleton in place, an error
 * collapses the card to a one-line apology, and a learner with no history at
 * all gets pointed at a starting point instead of an empty shell.
 */

type Lang = { zh: string; en: string };

const EMPTY_PLAN: DailyPlan = { continue_learning: null, recommendations: [] };

/** Where each continue kind reopens. Mirrors ``sessionRoute``'s mapping. */
function continueHref(kind: ContinueKind, ref: string): string {
  if (kind === "book") return `/mastery/${encodeURIComponent(ref)}`;
  if (kind === "reading") return `/reading/${encodeURIComponent(ref)}`;
  return `/chat/${encodeURIComponent(ref)}`;
}

export default function TodayLearningCard() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = (l: Lang) => (zh ? l.zh : l.en);

  const [plan, setPlan] = useState<DailyPlan | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getDailyPlan()
      .then((result) => {
        if (!cancelled) setPlan(result);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) {
    return (
      <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
        <p className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {tr({ zh: "今日学习暂时无法加载，稍后再试。", en: "Couldn't load today's plan — try again later." })}
        </p>
      </section>
    );
  }

  if (!plan) {
    return (
      <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 shrink-0 animate-pulse rounded-lg bg-[var(--muted)]" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-3.5 w-40 animate-pulse rounded bg-[var(--muted)]" />
            <div className="h-3 w-64 max-w-full animate-pulse rounded bg-[var(--muted)]" />
          </div>
        </div>
      </section>
    );
  }

  const { continue_learning: entry, recommendations } = plan;
  if (!entry && recommendations.length === 0) {
    return <StarterState tr={tr} />;
  }

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <header className="flex items-center gap-2">
        <GraduationCap size={16} strokeWidth={1.7} className="text-emerald-600 dark:text-emerald-400" />
        <h2 className="font-serif text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
          {tr({ zh: "今日学习", en: "Today's Learning" })}
        </h2>
      </header>

      {entry ? (
        <Link
          href={continueHref(entry.kind, entry.ref)}
          className="group mt-3 flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 p-3 transition-colors hover:border-[var(--foreground)]/20"
        >
          <span
            aria-hidden
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          >
            <PlayCircle size={17} strokeWidth={1.7} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[12px] leading-none text-[var(--muted-foreground)]">
              {tr({ zh: "继续上次", en: "Continue where you left off" })}
            </span>
            <span className="mt-1 block truncate text-[13.5px] font-medium leading-tight text-[var(--foreground)]">
              {entry.title || tr({ zh: "上次的学习", en: "Your last study" })}
            </span>
          </span>
        </Link>
      ) : null}

      {recommendations.length > 0 ? (
        <div className="mt-3">
          <p className="text-[12px] leading-none text-[var(--muted-foreground)]">
            {tr({ zh: "今日推荐 · 弱项巩固", en: "Recommended · weak points" })}
          </p>
          <ul className="mt-2 space-y-2">
            {recommendations.map((kp) => (
              <RecommendationRow key={kp.kp_id} kp={kp} tr={tr} />
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function RecommendationRow({
  kp,
  tr,
}: {
  kp: KpRecommendation;
  tr: (l: Lang) => string;
}) {
  const percent = Math.max(0, Math.min(100, Math.round(kp.mastery_level * 100)));
  return (
    <li>
      <Link
        href="/mastery"
        className="group flex items-center gap-3 rounded-lg border border-[var(--border)] p-2.5 transition-colors hover:border-[var(--foreground)]/20"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium leading-tight text-[var(--foreground)]">
            {kp.title}
          </span>
          <span className="mt-0.5 block truncate text-[11.5px] leading-snug text-[var(--muted-foreground)]">
            {kp.suggestion}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[12px] font-semibold leading-none tabular-nums text-[var(--foreground)]">
            {percent}%
          </span>
          <span className="mt-1 block text-[10px] leading-none text-[var(--muted-foreground)]">
            {tr({ zh: "掌握度", en: "mastery" })}
          </span>
        </span>
      </Link>
    </li>
  );
}

/** No history at all: the card becomes a pointer to a starting point. */
function StarterState({ tr }: { tr: (l: Lang) => string }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <header className="flex items-center gap-2">
        <Compass size={16} strokeWidth={1.7} className="text-emerald-600 dark:text-emerald-400" />
        <h2 className="font-serif text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
          {tr({ zh: "今日学习", en: "Today's Learning" })}
        </h2>
      </header>
      <p className="mt-2 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {tr({
          zh: "还没有学习记录 —— 打开一本书或建一条学习路径，今天就可以开始。",
          en: "No study history yet — open a book or start a learning path to begin today.",
        })}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Link
          href="/books"
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-1.5 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/20"
        >
          <BookOpen size={14} strokeWidth={1.7} />
          {tr({ zh: "从一本书开始", en: "Start from a book" })}
        </Link>
        <Link
          href="/mastery"
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-1.5 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/20"
        >
          <GraduationCap size={14} strokeWidth={1.7} />
          {tr({ zh: "建学习路径", en: "Start a learning path" })}
        </Link>
      </div>
    </section>
  );
}

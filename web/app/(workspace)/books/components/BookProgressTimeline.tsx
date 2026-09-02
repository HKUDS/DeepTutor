"use client";

import {
  Check,
  Loader2,
  AlertTriangle,
  Lightbulb,
  Search,
  Network,
  ScanSearch,
  BookMarked,
  LayoutList,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { BookProgress, StageId, StageView } from "@/lib/book-progress";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export interface BookProgressTimelineProps {
  progress: BookProgress;
  /** Durable chapter counts from the Book API (not replay-derived events). */
  pageCounts?: { ready: number; total: number };
  /** Compact mode — single-line horizontal pill strip (for reader header). */
  compact?: boolean;
  /** Mini mode — extra-thin floating chip (line + circles) for top-right. */
  mini?: boolean;
  className?: string;
}

const STAGE_ICONS: Record<
  StageId,
  React.ComponentType<{ className?: string }>
> = {
  ideation: Lightbulb,
  exploration: Search,
  synthesis: Network,
  critique: ScanSearch,
  overview: BookMarked,
  compilation: LayoutList,
};

// State → tailwind tokens. Uses theme css vars so it follows light/dark mode.
const STATE_TONE = {
  pending: {
    fg: "text-[var(--muted-foreground)]",
    bg: "bg-[var(--muted)]/40",
    ring: "ring-[var(--border)]",
    bar: "bg-[var(--border)]",
  },
  running: {
    fg: "text-sky-700 dark:text-sky-200",
    bg: "bg-gradient-to-br from-sky-400/20 to-indigo-400/15",
    ring: "ring-sky-400/60",
    bar: "bg-gradient-to-r from-sky-400 to-indigo-400",
  },
  completed: {
    fg: "text-emerald-700 dark:text-emerald-200",
    bg: "bg-emerald-500/10",
    ring: "ring-emerald-400/50",
    bar: "bg-gradient-to-r from-emerald-400 to-teal-400",
  },
  error: {
    fg: "text-rose-700 dark:text-rose-200",
    bg: "bg-rose-500/10",
    ring: "ring-rose-400/60",
    bar: "bg-rose-400",
  },
} as const;

function stageProgressFraction(progress: BookProgress): number {
  const { ordered, stages } = progress;
  let value = 0;
  for (const id of ordered) {
    const s = stages[id].state;
    if (s === "completed") value += 1;
    else if (s === "running") value += 0.5;
    else if (s === "error") value += 1;
  }
  return Math.min(1, value / ordered.length);
}

function StageIcon({ id, state }: { id: StageId; state: StageView["state"] }) {
  const cls = "h-3.5 w-3.5";
  if (state === "running") return <Loader2 className={`${cls} animate-spin`} />;
  if (state === "completed") return <Check className={cls} />;
  if (state === "error") return <AlertTriangle className={cls} />;
  const Icon = STAGE_ICONS[id];
  return <Icon className={cls} />;
}

function formatProgressMessage(message: string, t: Translate): string {
  if (!message) return "";
  const sourceSweep = message.match(
    /^Source sweep done — (\d+) queries, (\d+) chunks$/,
  );
  if (sourceSweep) {
    return t("Source sweep done — {{queries}} queries, {{chunks}} chunks", {
      queries: Number(sourceSweep[1]),
      chunks: Number(sourceSweep[2]),
    });
  }
  const spineReady = message.match(
    /^Spine ready — (\d+) chapters · (\d+) concepts$/,
  );
  if (spineReady) {
    return t("Spine ready — {{chapters}} chapters · {{concepts}} concepts", {
      chapters: Number(spineReady[1]),
      concepts: Number(spineReady[2]),
    });
  }
  return t(message);
}

function formatStageDetail(detail: string | undefined, t: Translate): string {
  if (!detail) return "";
  const sourceSweep = detail.match(/^(\d+) queries · (\d+) chunks$/);
  if (sourceSweep) {
    return t("{{queries}} queries · {{chunks}} chunks", {
      queries: Number(sourceSweep[1]),
      chunks: Number(sourceSweep[2]),
    });
  }
  const critique = detail.match(/^(\d+) rounds? · (\d+) issues?$/);
  if (critique) {
    const rounds = Number(critique[1]);
    const issues = Number(critique[2]);
    const key =
      rounds === 1
        ? issues === 1
          ? "{{rounds}} round · {{issues}} issue"
          : "{{rounds}} round · {{issues}} issues"
        : issues === 1
          ? "{{rounds}} rounds · {{issues}} issue"
          : "{{rounds}} rounds · {{issues}} issues";
    return t(key, { rounds, issues });
  }
  const synthesis = detail.match(/^(\d+) rounds? · (\d+) chapters?$/);
  if (synthesis) {
    const rounds = Number(synthesis[1]);
    const chapters = Number(synthesis[2]);
    const key =
      rounds === 1
        ? chapters === 1
          ? "{{rounds}} round · {{chapters}} chapter"
          : "{{rounds}} round · {{chapters}} chapters"
        : chapters === 1
          ? "{{rounds}} rounds · {{chapters}} chapter"
          : "{{rounds}} rounds · {{chapters}} chapters";
    return t(key, { rounds, chapters });
  }
  const spine = detail.match(/^(\d+) chapters · (\d+) concepts$/);
  if (spine) {
    return t("{{chapters}} chapters · {{concepts}} concepts", {
      chapters: Number(spine[1]),
      concepts: Number(spine[2]),
    });
  }
  const compilation = detail.match(/^(\d+) pages? · (\d+) blocks$/);
  if (compilation) {
    const pages = Number(compilation[1]);
    const blocks = Number(compilation[2]);
    return t(
      pages === 1
        ? "{{pages}} page · {{blocks}} blocks"
        : "{{pages}} pages · {{blocks}} blocks",
      { pages, blocks },
    );
  }
  return t(detail);
}

export default function BookProgressTimeline({
  progress,
  pageCounts,
  compact = false,
  mini = false,
  className = "",
}: BookProgressTimelineProps) {
  const { t } = useTranslation();
  const tr: Translate = (key, options) => t(key, options);
  const { ordered, stages, message } = progress;
  const fraction = stageProgressFraction(progress);
  const activeStage =
    ordered.find((id) => stages[id].state === "running") ||
    [...ordered].reverse().find((id) => stages[id].state === "completed") ||
    ordered[0];
  const activeView = stages[activeStage];
  const counters = collectCounters(progress, tr);
  const liveMessage = formatProgressMessage(message, tr);
  const activeDetail = formatStageDetail(activeView.detail, tr);

  // ── Mini mode: thin floating chip (top-right) ───────────────────────
  if (mini) {
    const allDone = fraction >= 1;
    const activeLabel = t(activeView.label);
    const tooltip = `${activeLabel}${activeDetail ? ` · ${activeDetail}` : ""}${
      liveMessage && message !== activeView.label ? ` · ${liveMessage}` : ""
    }`;
    return (
      <div
        className={`pointer-events-auto inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--card)]/90 px-2.5 py-1 text-[11px] shadow-sm backdrop-blur ${className}`}
        title={tooltip}
        aria-label={tooltip}
      >
        <Loader2
          className={`h-3 w-3 text-[var(--muted-foreground)] ${
            allDone ? "opacity-0" : "animate-spin"
          }`}
        />
        {/* line + circles strip */}
        <div className="relative flex items-center gap-1">
          {/* connector line behind the dots */}
          <div className="pointer-events-none absolute left-1.5 right-1.5 top-1/2 -z-0 h-px -translate-y-1/2 bg-[var(--border)]" />
          {ordered.map((id) => {
            const s = stages[id].state;
            const tone = STATE_TONE[s];
            return (
              <span
                key={id}
                title={`${t(stages[id].label)} · ${t(s)}`}
                className={`relative z-10 inline-flex h-3 w-3 items-center justify-center rounded-full ring-1 ${tone.ring} ${tone.bg}`}
              >
                {s === "running" && (
                  <span className="absolute inset-0 animate-ping rounded-full bg-sky-400/40" />
                )}
                {s === "completed" && (
                  <Check className="h-2 w-2 text-emerald-600 dark:text-emerald-300" />
                )}
                {s === "error" && (
                  <AlertTriangle className="h-2 w-2 text-rose-600 dark:text-rose-300" />
                )}
              </span>
            );
          })}
        </div>
        <span className="max-w-[160px] truncate text-[10.5px] text-[var(--muted-foreground)]">
          {activeLabel}
        </span>
        <span className="tabular-nums text-[10px] font-medium text-[var(--muted-foreground)]">
          {activeStage === "compilation" && pageCounts?.total
            ? t("{{ready}}/{{total}} pages", pageCounts)
            : `${Math.round(fraction * 100)}%`}
        </span>
      </div>
    );
  }

  if (compact) {
    return (
      <div
        className={`flex items-center gap-3 ${className}`}
        title={liveMessage || t(activeView.label)}
      >
        {/* Icon strip */}
        <div className="flex items-center gap-0.5">
          {ordered.map((id) => {
            const s = stages[id].state;
            const tone = STATE_TONE[s];
            return (
              <span
                key={id}
                title={`${t(stages[id].label)} · ${t(s)}`}
                className={`inline-flex h-5 w-5 items-center justify-center rounded-full ${tone.bg} ${tone.fg}`}
              >
                <StageIcon id={id} state={s} />
              </span>
            );
          })}
        </div>

        {/* Live caption */}
        <div className="min-w-0 flex-1 truncate text-[11px] text-[var(--muted-foreground)]">
          <span className="font-medium text-[var(--foreground)]">
            {t(activeView.label)}
          </span>
          {activeDetail && (
            <span className="ml-1.5 opacity-70">· {activeDetail}</span>
          )}
          {liveMessage && message !== activeView.label && (
            <span className="ml-1.5 opacity-70">· {liveMessage}</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`overflow-hidden rounded-2xl border border-[var(--border)] bg-gradient-to-br from-[var(--card)] to-[var(--card)]/60 shadow-sm ${className}`}
    >
      {/* ── Top hero row: animated progress bar + live caption ───────── */}
      <div className="px-4 pt-3.5">
        <div className="flex items-baseline justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
              <Loader2
                className={`h-3 w-3 ${fraction < 1 ? "animate-spin" : "opacity-0"}`}
              />
              {t("Generating book")}
            </div>
            <div className="mt-0.5 truncate text-sm font-medium text-[var(--foreground)]">
              {t(activeView.label)}
              {activeDetail && (
                <span className="ml-1.5 text-[12px] font-normal text-[var(--muted-foreground)]">
                  · {activeDetail}
                </span>
              )}
            </div>
            {liveMessage && message !== activeView.label && (
              <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                {liveMessage}
              </div>
            )}
          </div>
          <div className="text-right text-[11px] font-medium text-[var(--muted-foreground)] tabular-nums">
            {Math.round(fraction * 100)}%
          </div>
        </div>

        {/* Continuous gradient progress bar */}
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-[var(--muted)]/60">
          <div
            className="h-full rounded-full bg-gradient-to-r from-sky-400 via-indigo-400 to-emerald-400 transition-all duration-700 ease-out"
            style={{ width: `${Math.max(2, fraction * 100)}%` }}
          />
        </div>
      </div>

      {/* ── Segmented stage strip ──────────────────────────────────── */}
      <div className="px-3 pb-3 pt-3">
        <div className="grid grid-cols-6 gap-1.5">
          {ordered.map((id) => {
            const stage = stages[id];
            const tone = STATE_TONE[stage.state];
            const isActive = stage.state === "running";
            return (
              <div
                key={id}
                title={`${t(stage.label)} — ${t(stage.description)}`}
                className={`group relative flex items-center gap-1.5 rounded-lg px-1.5 py-1.5 ring-1 transition-all ${
                  isActive
                    ? `${tone.bg} ${tone.ring}`
                    : `${tone.bg} ${tone.ring} opacity-90`
                }`}
              >
                <span
                  className={`inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full ${tone.bg} ${tone.fg}`}
                >
                  <StageIcon id={id} state={stage.state} />
                </span>
                <div className="min-w-0 flex-1">
                  <div
                    className={`truncate text-[11px] font-medium ${tone.fg}`}
                  >
                    {t(stage.label)}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {counters.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-[var(--border)] pt-2.5 text-[11px]">
            {counters.map((item) => (
              <div
                key={item.label}
                className="inline-flex items-baseline gap-1 text-[var(--muted-foreground)]"
              >
                <span className="font-semibold tabular-nums text-[var(--foreground)]">
                  {item.value}
                </span>
                <span className="opacity-80">{item.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function collectCounters(
  progress: BookProgress,
  t: Translate,
): { label: string; value: string | number }[] {
  const items: { label: string; value: string | number }[] = [];
  if (progress.exploration.queryCount > 0) {
    items.push({ label: t("queries"), value: progress.exploration.queryCount });
  }
  if (progress.exploration.chunkCount > 0) {
    items.push({ label: t("chunks"), value: progress.exploration.chunkCount });
  }
  if (progress.synthesis.chapterCount > 0) {
    items.push({
      label: t("chapters"),
      value: progress.synthesis.chapterCount,
    });
  }
  if (progress.synthesis.conceptNodes > 0) {
    items.push({
      label: t("concepts"),
      value: `${progress.synthesis.conceptNodes}/${progress.synthesis.conceptEdges}`,
    });
  }
  if (progress.compilation.blocksReady > 0) {
    items.push({
      label: t("blocks ready"),
      value: progress.compilation.blocksReady,
    });
  }
  if (progress.compilation.pagesReady > 0) {
    items.push({
      label: t("pages ready"),
      value: progress.compilation.pagesReady,
    });
  }
  if (progress.compilation.blocksError > 0) {
    items.push({
      label: t("block errors"),
      value: progress.compilation.blocksError,
    });
  }
  return items;
}

"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export type ContextBudgetSegment = { key: string; tokens: number };

export type ContextBudget = {
  window: number;
  window_estimated?: boolean;
  used_tokens: number;
  free_tokens: number;
  model?: string;
  counter?: string;
  deferred_tool_count?: number;
  segments: ContextBudgetSegment[];
};

/**
 * Mid-tone hues only. The swatches and the stacked bar sit on --popover,
 * which flips between near-white and near-black, so anything very light or
 * very dark vanishes in one of the two themes. Red is deliberately absent:
 * a segment being large is information, not an error.
 */
const SEGMENT_COLORS: Record<string, string> = {
  messages: "#6366f1",
  system_prompt: "#0ea5e9",
  system_tools: "#14b8a6",
  mcp_tools: "#10b981",
  tool_manifest: "#84cc16",
  extended_tools: "#f59e0b",
  persona_style: "#f97316",
  partner_turn_policy: "#d946ef",
  memory: "#a855f7",
  knowledge_base_note: "#8b5cf6",
  skills: "#06b6d4",
  sources: "#0891b2",
  notebooks: "#e879a3",
  workspace: "#65a30d",
  capability: "#64748b",
};

const FALLBACK_COLORS = [
  "#6366f1",
  "#0ea5e9",
  "#14b8a6",
  "#f59e0b",
  "#a855f7",
  "#64748b",
];

function segmentColor(key: string): string {
  const known = SEGMENT_COLORS[key];
  if (known) return known;
  // An unrecognized key means the backend grew a segment this build doesn't
  // know about; hash it to a stable colour instead of dropping the row.
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length];
}

/**
 * Mirrors formatCompactTokens in components/settings/ServiceConfigEditor.tsx,
 * but keeps one decimal and a lowercase "k" so the header reads like a budget
 * ("895.3k / 1M") rather than a spec sheet. Copied rather than shared because
 * that helper is module-private over there.
 */
function formatTokens(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  const compact = (scaled: number) => scaled.toFixed(1).replace(/\.0$/, "");
  if (value >= 1_000_000) return `${compact(value / 1_000_000)}M`;
  if (value >= 1_000) return `${compact(value / 1_000)}k`;
  return String(Math.round(value));
}

function formatPercent(share: number): string {
  if (!Number.isFinite(share) || share <= 0) return "0%";
  if (share < 1) return "<1%";
  if (share < 10) return `${share.toFixed(1).replace(/\.0$/, "")}%`;
  return `${Math.round(share)}%`;
}

/**
 * Tiny ring gauge; inherits the chip's colour so tone changes carry over.
 * Sized 16 to sit level with the lucide icons the neighbouring composer
 * selectors render at `size={16}`.
 */
function UsageRing({ share }: { share: number }) {
  const radius = 6.5;
  const circumference = 2 * Math.PI * radius;
  const filled = Math.min(100, Math.max(0, share)) / 100;
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="-rotate-90 shrink-0"
    >
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="opacity-25"
      />
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - filled)}
      />
    </svg>
  );
}

function SegmentRow({
  color,
  label,
  tokens,
  share,
  bordered = false,
}: {
  color: string;
  label: string;
  tokens: number;
  share: number;
  bordered?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={`h-2 w-2 shrink-0 rounded-[2px] ${
          bordered ? "border border-[var(--border)]" : ""
        }`}
        style={{ backgroundColor: color }}
      />
      <span className="min-w-0 flex-1 truncate text-[11.5px] text-[var(--foreground)]">
        {label}
      </span>
      <span className="shrink-0 text-[11.5px] tabular-nums text-[var(--muted-foreground)]">
        {formatTokens(tokens)}
      </span>
      <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-[var(--muted-foreground)]/70">
        {formatPercent(share)}
      </span>
    </div>
  );
}

/**
 * Context-window breakdown for the just-finished turn (composer toolbar).
 *
 * Pure presentation: the numbers are measured server-side from the request
 * that was actually sent, so this component only formats what it is handed.
 * Every number here is an estimate — the footnotes say so explicitly rather
 * than letting a confident-looking bar imply precision we don't have.
 */
export default function ContextBudgetChip({
  budget,
}: {
  budget: ContextBudget;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (rootRef.current && !rootRef.current.contains(target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // The caller's guard is `typeof === "number"`, which NaN also satisfies, so
  // clamp here rather than let a NaN reach the divisor and print "NaN%".
  const used = Number.isFinite(budget.used_tokens)
    ? Math.max(0, budget.used_tokens)
    : 0;
  // A zero/absent window would make every share NaN; fall back to what we
  // measured so the popover still says something true.
  const total =
    Number.isFinite(budget.window) && budget.window > 0
      ? budget.window
      : Math.max(used, 1);
  const free = Number.isFinite(budget.free_tokens)
    ? Math.max(0, budget.free_tokens)
    : Math.max(0, total - used);
  const usedShare = (used / total) * 100;
  const usedPercentLabel = `${Math.round(usedShare)}%`;
  // Backend already sorts descending and drops empties; filter defensively
  // and keep its order. The key is required for the colour hash and the label
  // lookup, so a row without a usable one is dropped rather than thrown on.
  const segments = (budget.segments ?? []).filter(
    (segment) =>
      segment &&
      typeof segment.key === "string" &&
      segment.key.length > 0 &&
      Number.isFinite(segment.tokens) &&
      segment.tokens > 0,
  );

  const estimatedWindow = budget.window_estimated === true;
  const heuristicCounter = budget.counter === "heuristic";
  const deferredCount = budget.deferred_tool_count ?? 0;
  const hasNotes = estimatedWindow || heuristicCounter || deferredCount > 0;
  const nearFull = usedShare >= 90;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-label={t("contextBudget.chipAria", { percent: usedPercentLabel })}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2 text-[14px] font-medium tabular-nums transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
          open
            ? "bg-[var(--muted)] text-[var(--foreground)]"
            : nearFull
              ? "text-amber-500 hover:bg-amber-500/10"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
        }`}
      >
        <UsageRing share={usedShare} />
        <span>{usedPercentLabel}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={t("contextBudget.title")}
          style={{ transformOrigin: "bottom right" }}
          className="dt-popup-up absolute bottom-full right-0 z-50 mb-1.5 w-[min(300px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md"
        >
          <div className="px-3 pb-2.5 pt-2.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="shrink-0 text-[10.5px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("contextBudget.title")}
              </span>
              {budget.model ? (
                <span className="min-w-0 truncate text-[10.5px] text-[var(--muted-foreground)]/70">
                  {budget.model}
                </span>
              ) : null}
            </div>
            <div className="mt-1 flex items-baseline gap-1.5">
              <span className="text-[12.5px] font-semibold tabular-nums text-[var(--foreground)]">
                {t("contextBudget.usage", {
                  used: formatTokens(used),
                  total: formatTokens(total),
                  percent: usedPercentLabel,
                })}
              </span>
              {estimatedWindow ? (
                <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                  {t("contextBudget.estimated")}
                </span>
              ) : null}
            </div>
            <div className="mt-2 flex h-1.5 w-full overflow-hidden rounded-full bg-[var(--muted)]">
              {segments.map((segment) => (
                <div
                  key={segment.key}
                  style={{
                    width: `${Math.min(100, (segment.tokens / total) * 100)}%`,
                    backgroundColor: segmentColor(segment.key),
                  }}
                />
              ))}
            </div>
          </div>

          <div className="max-h-[240px] space-y-1.5 overflow-y-auto px-3 pb-2.5">
            {segments.map((segment) => (
              <SegmentRow
                key={segment.key}
                color={segmentColor(segment.key)}
                label={t(`contextBudget.segment.${segment.key}`, {
                  defaultValue: segment.key.replace(/_/g, " "),
                })}
                tokens={segment.tokens}
                share={(segment.tokens / total) * 100}
              />
            ))}
            <SegmentRow
              bordered
              color="var(--muted)"
              label={t("contextBudget.freeSpace")}
              tokens={free}
              share={(free / total) * 100}
            />
          </div>

          {hasNotes && (
            <div className="space-y-1 border-t border-[var(--border)]/60 px-3 py-2 text-[10.5px] leading-[1.5] text-[var(--muted-foreground)]/80">
              {estimatedWindow && (
                <p>{t("contextBudget.note.estimatedWindow")}</p>
              )}
              {heuristicCounter && (
                <p>{t("contextBudget.note.heuristicCounter")}</p>
              )}
              {deferredCount > 0 && (
                <p>
                  {t("contextBudget.note.deferredTools", {
                    count: deferredCount,
                  })}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

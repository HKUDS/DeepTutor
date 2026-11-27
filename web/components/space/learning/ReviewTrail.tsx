"use client";

import Tooltip from "@/shared/ui/Tooltip";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock3,
  Copy,
  Loader2,
  PencilRuler,
  Play,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useState } from "react";

import type {
  ReviewIntervalType,
  ReviewStrategy,
  ReviewStrategyInput,
  TopicReview,
} from "@/lib/learning-api";

import { formatRelative } from "./format";

const RETENTION_TARGETS = [0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 0.99];
const INTERVAL_TYPES: ReviewIntervalType[] = [
  "memory",
  "concept",
  "procedure",
  "design",
];
const BASELINE_INTERVALS: Record<ReviewIntervalType, number[]> = {
  memory: [0, 1, 3, 7, 14, 30, 60],
  concept: [3, 7, 14, 30],
  procedure: [3, 7, 14],
  design: [14, 28],
};

type StrategyForm = {
  name: string;
  intervals: Record<ReviewIntervalType, string>;
};

function formFromStrategy(strategy: ReviewStrategy | undefined): StrategyForm {
  return {
    name: strategy && !strategy.builtin ? strategy.name : `${strategy?.name ?? "Default"} copy`,
    intervals: Object.fromEntries(
      INTERVAL_TYPES.map((type) => [
        type,
        (strategy?.intervals[type] ?? BASELINE_INTERVALS[type]).join(","),
      ]),
    ) as Record<ReviewIntervalType, string>,
  };
}

function parseStrategyForm(form: StrategyForm): ReviewStrategyInput | null {
  const name = form.name.trim();
  if (!name) return null;
  const intervals = {} as Record<ReviewIntervalType, number[]>;
  for (const type of INTERVAL_TYPES) {
    const raw = form.intervals[type].trim();
    if (!/^\d+(?:\s*,\s*\d+)*$/.test(raw)) return null;
    const rounds = raw.split(",").map((value) => Number(value.trim()));
    if (
      rounds.length > 16 ||
      rounds.some((days) => days > 365) ||
      rounds.some((days, index) => index > 0 && days < rounds[index - 1]) ||
      rounds.some((days, index) => index > 0 && days === 0)
    ) {
      return null;
    }
    intervals[type] = rounds;
  }
  return { name, intervals, desired_retention: null };
}

export function ReviewTrail({
  reviews,
  desiredRetention,
  retentionBusy,
  retentionError,
  onRetentionChange,
  strategies,
  selectedStrategyId,
  strategyLoading,
  strategyError,
  strategyBusy,
  onStrategyChange,
  onRetryStrategies,
  onStrategySave,
  onStrategyDuplicate,
  onStrategyDelete,
  zh,
  onSelect,
  onStartReview,
}: {
  reviews: TopicReview[];
  desiredRetention: number;
  retentionBusy: boolean;
  retentionError: string | null;
  onRetentionChange: (value: number) => void;
  strategies: ReviewStrategy[];
  selectedStrategyId: string;
  strategyLoading: boolean;
  strategyError: string | null;
  strategyBusy: boolean;
  onStrategyChange: (templateId: string) => void;
  onRetryStrategies: () => void;
  onStrategySave: (
    input: ReviewStrategyInput,
    templateId?: string,
  ) => Promise<void>;
  onStrategyDuplicate: (templateId: string, name: string) => Promise<void>;
  onStrategyDelete: (templateId: string) => Promise<void>;
  zh: boolean;
  onSelect: (objectiveId: string) => void;
  onStartReview: (objectiveId: string, name: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [form, setForm] = useState<StrategyForm>(() =>
    formFromStrategy(undefined),
  );
  const [formError, setFormError] = useState<string | null>(null);
  const selectedStrategy = strategies.find(
    (strategy) => strategy.template_id === selectedStrategyId,
  );
  const editingCustom = Boolean(selectedStrategy && !selectedStrategy.builtin);
  const due = reviews.filter((review) => review.due);
  const ordered = [...reviews].sort(
    (left, right) =>
      Number(right.due) - Number(left.due) ||
      (left.due
        ? right.forgetting_risk - left.forgetting_risk
        : left.due_at - right.due_at),
  );
  const visible = expanded ? ordered : ordered.slice(0, 5);
  const retentionTargets = RETENTION_TARGETS.includes(desiredRetention)
    ? RETENTION_TARGETS
    : [...RETENTION_TARGETS, desiredRetention].sort((a, b) => a - b);

  const submitStrategy = async () => {
    const input = parseStrategyForm(form);
    if (!input) {
      setFormError(
        t("Use 1-16 non-decreasing whole-day rounds from 0-365 in every row."),
      );
      return;
    }
    setFormError(null);
    await onStrategySave(input, editingCustom ? selectedStrategyId : undefined);
    setEditorOpen(false);
  };

  return (
    <section className="dt-panel min-h-0 flex-col lg:max-h-[min(34vh,300px)] lg:shrink-0">
      <div className="dt-panel-head flex-wrap justify-between gap-3">
        <Tooltip label={t("Scheduled by your forgetting curve")} as="div" side="top">
          <h2 tabIndex={0} className="text-[13px] font-semibold text-[var(--foreground)]">
            {t("Review plan")}
          </h2>
        </Tooltip>
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <label className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
            <span>{t("Strategy")}</span>
            <select
              value={selectedStrategyId}
              onChange={(event) => {
                setEditorOpen(false);
                onStrategyChange(event.target.value);
              }}
              disabled={strategyLoading || strategyBusy}
              className="h-7 max-w-36 rounded-md border border-[var(--border)] bg-[var(--card)] px-1.5 text-[11px] font-medium text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40 disabled:opacity-60"
            >
              <option value="">{t("Default")}</option>
              {strategyLoading && <option>{t("Loading…")}</option>}
              {strategies.map((strategy) => (
                <option key={strategy.template_id} value={strategy.template_id}>
                  {strategy.name}
                </option>
              ))}
            </select>
          </label>
          <Tooltip
            label={editorOpen ? t("Close strategy editor") : t("Edit strategy")}
          >
            <button
              type="button"
              onClick={() => {
                const next = !editorOpen;
                setEditorOpen(next);
                if (next) {
                  setForm(formFromStrategy(selectedStrategy));
                  setFormError(null);
                }
              }}
              disabled={strategyLoading}
              aria-pressed={editorOpen}
              aria-label={editorOpen ? t("Close strategy editor") : t("Edit strategy")}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[var(--border)] text-[var(--muted-foreground)] transition hover:text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40 disabled:opacity-60"
            >
              <PencilRuler className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </Tooltip>
          <label className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
            <span>{t("Recall target")}</span>
            <select
              value={desiredRetention}
              onChange={(event) => onRetentionChange(Number(event.target.value))}
              disabled={retentionBusy}
              aria-describedby="review-retention-hint"
              className="h-7 rounded-md bg-[var(--background)] px-1.5 text-[11px] font-medium tabular-nums text-[var(--foreground)] shadow-[0_0_0_1px_rgb(0_0_0/0.06)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40 disabled:opacity-60"
            >
              {retentionTargets.map((target) => (
                <option key={target} value={target}>
                  {Math.round(target * 1000) / 10}%
                </option>
              ))}
            </select>
          </label>
          {(retentionBusy || strategyBusy) && (
            <span className="inline-flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              <span className="sr-only">{t("Saving…")}</span>
            </span>
          )}
          <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
            {due.length} {t("due")}
          </span>
        </div>
      </div>
      {!editorOpen && strategies.every((strategy) => strategy.builtin) && (
        <p className="shrink-0 px-4 pt-2 text-[10px] text-[var(--muted-foreground)]">
          {t("No custom strategies yet")}
        </p>
      )}
      <p id="review-retention-hint" className="shrink-0 px-4 text-[11px] text-[var(--muted-foreground)]">
        {t("Higher targets schedule reviews sooner.")}
      </p>
      {strategyError && (
        <div
          role="alert"
          className="flex items-center gap-2 px-4 pt-1 text-[11px] text-red-600 dark:text-red-400"
        >
          <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{strategyError}</span>
          <button
            type="button"
            onClick={onRetryStrategies}
            className="inline-flex items-center gap-1 font-medium underline"
          >
            <RotateCcw className="h-3 w-3" aria-hidden="true" />
            {t("Try again")}
          </button>
        </div>
      )}
      {editorOpen && (
        <div className="max-h-36 shrink-0 overflow-y-auto border-b border-[var(--border)] px-4 py-3">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <label className="text-[10px] font-medium text-[var(--muted-foreground)] sm:col-span-2 xl:col-span-4">
              {t("Name")}
              <input
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                className="mt-1 h-7 w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2 text-[11px] text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40"
              />
            </label>
            {INTERVAL_TYPES.map((type) => (
              <label
                key={type}
                className="text-[10px] font-medium capitalize text-[var(--muted-foreground)]"
              >
                {t(type)} {t("rounds (days)")}
                <input
                  value={form.intervals[type]}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      intervals: {
                        ...current.intervals,
                        [type]: event.target.value,
                      },
                    }))
                  }
                  className="mt-1 h-7 w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2 font-mono text-[11px] normal-case text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40"
                />
              </label>
            ))}
          </div>
          {formError && (
            <p
              role="alert"
              className="mt-2 text-[11px] text-red-600 dark:text-red-400"
            >
              {formError}
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void submitStrategy()}
              disabled={strategyBusy}
              className="inline-flex h-7 items-center gap-1.5 rounded-md bg-[var(--primary)] px-2.5 text-[11px] font-medium text-[var(--primary-foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40 disabled:opacity-60"
            >
              <Check className="h-3 w-3" aria-hidden="true" />
              {editingCustom ? t("Save") : t("Save as custom")}
            </button>
            {selectedStrategy && (
              <Tooltip label={t("Duplicate")}>
                <button
                  type="button"
                  onClick={() =>
                    void onStrategyDuplicate(
                      selectedStrategy.template_id,
                      `${selectedStrategy.name} copy`,
                    ).then(() => setEditorOpen(false))
                  }
                  disabled={strategyBusy}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40 disabled:opacity-60"
                >
                  <Copy className="h-3 w-3" aria-hidden="true" />
                </button>
              </Tooltip>
            )}
            {editingCustom && (
              <Tooltip label={t("Delete and use default")}>
                <button
                  type="button"
                  onClick={() =>
                    void onStrategyDelete(selectedStrategyId).then(() =>
                      setEditorOpen(false),
                    )
                  }
                  disabled={strategyBusy}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-red-200 text-red-600 hover:bg-red-500/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500/40 disabled:opacity-60 dark:border-red-900"
                >
                  <Trash2 className="h-3 w-3" aria-hidden="true" />
                </button>
              </Tooltip>
            )}
          </div>
        </div>
      )}
      {retentionError && (
        <p
          role="alert"
          className="shrink-0 px-4 pt-1 text-[11px] text-red-600 dark:text-red-400"
        >
          {retentionError}
        </p>
      )}
      {reviews.length === 0 ? (
        <div className="flex shrink-0 items-start gap-2 px-4 py-3.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
          {t(
            "Nothing is due today. Keep going — reviews will resurface at the right time.",
          )}
        </div>
      ) : (
        <div className="dt-panel-body min-h-0 overflow-y-auto pt-1">
          {visible.map((review) => (
            <div
              key={review.id}
              className="group flex items-center gap-2 rounded-xl px-2.5 py-2 transition hover:bg-[rgb(var(--dt-ink,55_53_47)/0.045)]"
            >
              <Clock3
                className={`h-3.5 w-3.5 shrink-0 ${review.due ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
              />
              <button
                type="button"
                onClick={() => onSelect(review.knowledge_point_id)}
                className="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40"
              >
                <span className="block truncate text-xs font-medium text-[var(--foreground)]">
                  {review.knowledge_point_name}
                </span>
                <span className="text-[10px] text-[var(--muted-foreground)]">
                  {review.due
                    ? t("Ready now")
                    : formatRelative(review.due_at, zh)}
                  <span className="ml-2">
                    {t("risk {{risk}}%", {
                      risk: Math.round(review.forgetting_risk * 100),
                    })}
                  </span>
                  {review.recent_failure && (
                    <span className="ml-2 text-red-600 dark:text-red-400">
                      {t("recent failure")}
                    </span>
                  )}
                </span>
                <span className="block truncate text-[10px] text-[var(--muted-foreground)]">
                  {review.reason}
                </span>
              </button>
              <button
                type="button"
                aria-label={t("Start review for {{name}}", {
                  name: review.knowledge_point_name,
                })}
                onClick={() =>
                  onStartReview(review.knowledge_point_id, review.knowledge_point_name)
                }
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40"
              >
                <Play className="h-3 w-3" />
              </button>
              <ArrowRight className="hidden h-3 w-3 text-[var(--muted-foreground)] transition-transform group-hover:translate-x-0.5 sm:block" />
            </div>
          ))}
          {reviews.length > 5 && (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="mt-1 w-full rounded-md px-2.5 py-2 text-left text-[11px] font-medium text-[var(--primary)] hover:bg-[var(--muted)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40"
            >
              {expanded
                ? t("Show fewer")
                : t("Show all {{count}} reviews", { count: reviews.length })}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

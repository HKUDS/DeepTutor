"use client";

import { ArrowRight, CheckCircle2, Clock3, Loader2, Play } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useState } from "react";

import type { TopicReview } from "@/lib/learning-api";

import { formatRelative } from "./format";

const RETENTION_TARGETS = [0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 0.99];

export function ReviewTrail({
  reviews,
  desiredRetention,
  retentionBusy,
  retentionError,
  onRetentionChange,
  zh,
  onSelect,
  onStartReview,
}: {
  reviews: TopicReview[];
  desiredRetention: number;
  retentionBusy: boolean;
  retentionError: string | null;
  onRetentionChange: (value: number) => void;
  zh: boolean;
  onSelect: (objectiveId: string) => void;
  onStartReview: (objectiveId: string, name: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
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
  return (
    <section className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--secondary)] px-4 py-2.5">
        <h2
          className="text-[12px] font-semibold text-[var(--foreground)]"
          title={t("Scheduled by your forgetting curve")}
        >
          {t("Review plan")}
        </h2>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
            <span>{t("Recall target")}</span>
            <select
              value={desiredRetention}
              onChange={(event) => onRetentionChange(Number(event.target.value))}
              disabled={retentionBusy}
              aria-describedby="review-retention-hint"
              className="h-7 rounded-md border border-[var(--border)] bg-[var(--card)] px-1.5 text-[11px] font-medium tabular-nums text-[var(--foreground)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40 disabled:opacity-60"
            >
              {retentionTargets.map((target) => (
                <option key={target} value={target}>
                  {Math.round(target * 1000) / 10}%
                </option>
              ))}
            </select>
          </label>
          {retentionBusy && (
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
      <p id="review-retention-hint" className="px-4 pt-2 text-[10px] text-[var(--muted-foreground)]">
        {t("Higher targets schedule reviews sooner.")}
      </p>
      {retentionError && (
        <p role="alert" className="px-4 pt-1 text-[11px] text-red-600 dark:text-red-400">
          {retentionError}
        </p>
      )}
      {reviews.length === 0 ? (
        <div className="flex items-start gap-2 px-4 py-3.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
          {t(
            "Nothing is due today. Keep going — reviews will resurface at the right time.",
          )}
        </div>
      ) : (
        <div className="p-2">
          {visible.map((review) => (
            <div
              key={review.id}
              className="group flex items-center gap-2 rounded-lg px-2.5 py-2 transition hover:bg-[var(--muted)]"
            >
              <Clock3
                className={`h-3.5 w-3.5 shrink-0 ${review.due ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
              />
              <button
                type="button"
                onClick={() => onSelect(review.knowledge_point_id)}
                className="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40"
                title={review.reason}
              >
                <span className="block truncate text-xs font-medium text-[var(--foreground)]">
                  {review.knowledge_point_name}
                </span>
                <span className="text-[10px] text-[var(--muted-foreground)]">
                  {review.due
                    ? t("Ready now")
                    : formatRelative(review.due_at, zh)}
                  <span className="ml-2">{t("risk {{risk}}%", { risk: Math.round(review.forgetting_risk * 100) })}</span>
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
                aria-label={t("Start review for {{name}}", { name: review.knowledge_point_name })}
                onClick={() => onStartReview(review.knowledge_point_id, review.knowledge_point_name)}
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
              {expanded ? t("Show fewer") : t("Show all {{count}} reviews", { count: reviews.length })}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

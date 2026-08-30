"use client";

import { ArrowRight, BellRing, CheckCircle2, Clock3 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TopicReview } from "@/lib/learning-api";

import { formatRelative, type Translate } from "./format";

export function ReviewTrail({
  reviews,
  zh,
  onSelect,
}: {
  reviews: TopicReview[];
  zh: boolean;
  onSelect: (objectiveId: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--secondary)] px-4 py-2.5">
        <h2
          className="text-[12px] font-semibold text-[var(--foreground)]"
          title={t("Scheduled by your forgetting curve")}
        >
          {t("Review plan")}
        </h2>
        <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
          {reviews.length}
        </span>
      </div>
      {reviews.length === 0 ? (
        <div className="flex items-start gap-2 px-4 py-3.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
          {t(
            "Nothing is due today. Keep going — reviews will resurface at the right time.",
          )}
        </div>
      ) : (
        <div className="p-2">
          {reviews.slice(0, 5).map((review) => (
            <button
              key={review.id}
              type="button"
              onClick={() => onSelect(review.knowledge_point_id)}
              className="group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition hover:bg-[var(--muted)]"
            >
              <Clock3
                className={`h-3.5 w-3.5 shrink-0 ${review.due ? "text-[var(--muted-foreground)]" : "text-[var(--muted-foreground)]"}`}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-[var(--foreground)]">
                  {review.knowledge_point_name}
                </span>
                <span className="text-[10px] text-[var(--muted-foreground)]">
                  {review.due
                    ? t("Ready now")
                    : formatRelative(review.due_at, zh)}
                </span>
              </span>
              <ArrowRight className="h-3 w-3 text-[var(--muted-foreground)] transition-transform group-hover:translate-x-0.5" />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

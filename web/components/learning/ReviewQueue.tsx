"use client";

import { CalendarClock } from "lucide-react";
import type { ReviewsPayload } from "@/lib/feynman-learning";
import { dueReviewTasks, reviewTaskLabel } from "./contract";
import { SectionHead, StatusTag } from "./ui";
import type { TrFn } from "./locale";

/**
 * Learning Space · delayed reteach queue (§13.2, §17.6 FT-04).
 * Every knowledge type reads from the same unified scheduler queue; the band
 * distinguishes provisional (queued) from stable mastery and surfaces failure
 * gaps by priority.
 */
export function ReviewQueue({
  reviews,
  kpName,
  tr,
  onOpenKp,
}: {
  reviews: ReviewsPayload | null;
  kpName: (kpId: string) => string;
  tr: TrFn;
  onOpenKp: (kpId: string) => void;
}) {
  if (!reviews) return null;
  const due = dueReviewTasks(reviews.due_reviews.length ? reviews.due_reviews : reviews.reviews);
  const stableIds = new Set(reviews.needs_revision);

  return (
    <section className="fw-learning-space" data-testid="review-queue">
      <div className="fw-learning-head">
        <div className="fw-panel-title">
          <strong>{tr("Learning Space · 待延迟复教", "Learning Space · delayed reteach")}</strong>
          <span className="text-xs text-[var(--fw-muted)]">
            {tr("所有知识类型统一进入 scheduler", "All knowledge types share one scheduler queue")}
          </span>
        </div>
        <StatusTag color="blue">
          {reviews.due_count} {tr("项到期", "due")}
        </StatusTag>
      </div>

      <div className="fw-learning-grid">
        <div className="grid gap-1.5" data-testid="review-queue-list">
          <SectionHead
            label={tr("队列", "Queue")}
            trailing={
              <span className="text-xs text-[var(--fw-muted)]">
                {tr("知识点 / 类型 / 到期 / 状态", "KP / type / due / status")}
              </span>
            }
          />
          {due.length === 0 ? (
            <span className="text-sm text-[var(--fw-muted)]">
              {tr("暂无待复习项", "Nothing due right now.")}
            </span>
          ) : (
            due.map((task) => (
              <button
                key={task.id}
                type="button"
                className="fw-queue-row"
                onClick={() => onOpenKp(task.knowledge_point_id)}
                data-testid="review-row"
              >
                <strong className="min-w-0 truncate">{kpName(task.knowledge_point_id)}</strong>
                <span className="fw-queue-meta">
                  {task.knowledge_type} · {reviewTaskLabel(task)}
                </span>
                <span className="fw-queue-meta">
                  {new Date(task.due_at * 1000).toLocaleString()}
                </span>
                <StatusTag color={stableIds.has(task.knowledge_point_id) ? "coral" : "blue"}>
                  {stableIds.has(task.knowledge_point_id)
                    ? tr("待修订", "needs revision")
                    : tr("待延迟复教", "reteach due")}
                </StatusTag>
              </button>
            ))
          )}
        </div>

        <div className="grid gap-1.5">
          <SectionHead label={tr("稳定掌握", "Stable mastery")} />
          {reviews.needs_revision.length === 0 ? (
            <span className="text-sm text-[var(--fw-muted)]">
              {tr("暂无稳定掌握条目", "No stable mastery entries yet.")}
            </span>
          ) : (
            reviews.needs_revision.map((kpId) => (
              <div key={kpId} className="fw-stable-row">
                <StatusTag color="green">{tr("稳定掌握", "Stable mastery")}</StatusTag>
                <strong>{kpName(kpId)}</strong>
                <span className="fw-queue-meta flex items-center gap-1">
                  <CalendarClock className="h-3.5 w-3.5" />
                  {tr("延迟复教已通过", "reteach passed")}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

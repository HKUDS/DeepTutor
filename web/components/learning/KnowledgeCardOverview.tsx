"use client";

import { FileText } from "lucide-react";
import type { KnowledgeCardView } from "@/lib/knowledge-card-api";
import { cardActions, pendingCards } from "./knowledgeCard";
import { CardStatusTag } from "./KnowledgeCardPanel";
import { SectionHead, StatusTag } from "./ui";
import type { TrFn } from "./locale";

/**
 * Learning Space · knowledge-card aggregate (§13.2).
 *
 * Non-blocking summary of every pending/published card across the path so a
 * learner can pick up a draft, a failed publication or a retract later —
 * processing a card is never a prerequisite for continuing to learn.
 */
export function KnowledgeCardOverview({
  cards,
  kpName,
  tr,
  busy,
  onReview,
  onDiscard,
}: {
  cards: KnowledgeCardView[];
  kpName: (kpId: string) => string;
  tr: TrFn;
  busy: Record<string, boolean>;
  onReview: (cardId: string) => void;
  onDiscard: (cardId: string) => void;
}) {
  const pending = pendingCards(cards);
  return (
    <section className="fw-learning-space" data-testid="knowledge-card-overview">
      <div className="fw-learning-head">
        <div className="fw-panel-title">
          <strong className="flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5 text-[var(--fw-amber)]" />
            {tr("知识卡片", "Knowledge cards")}
          </strong>
          <span className="text-xs text-[var(--fw-muted)]">
            {tr(
              "待处理卡片不会阻塞学习，可稍后处理。",
              "Pending cards never block learning — handle them later.",
            )}
          </span>
        </div>
        <StatusTag color="amber">
          {pending.length} {tr("待处理", "pending")}
        </StatusTag>
      </div>

      <div className="fw-learning-grid">
        <div className="grid gap-1.5" data-testid="knowledge-card-overview-list">
          <SectionHead
            label={tr("待审核 / 发布", "Review / publish")}
            trailing={
              <span className="text-xs text-[var(--fw-muted)]">
                {tr("知识点 / 状态 / 来源 · 证据 · 图片", "KP / status / sources · evidence · images")}
              </span>
            }
          />
          {pending.length === 0 ? (
            <span className="text-sm text-[var(--fw-muted)]">
              {tr("暂无待处理知识卡片", "No pending knowledge cards.")}
            </span>
          ) : (
            pending.map((card) => {
              const actions = cardActions(card);
              return (
                <div key={card.card_id} className="fw-kc-overview-row" data-testid="kc-overview-row">
                  <div className="min-w-0">
                    <strong className="block text-sm break-all">
                      {card.title || tr("（未命名草稿）", "(untitled draft)")}
                    </strong>
                    <span className="fw-queue-meta block">{kpName(card.knowledge_point_id)}</span>
                    <span className="fw-queue-meta block">
                      {card.source_count} {tr("来源", "sources")} · {card.evidence_count}{" "}
                      {tr("证据", "evidence")} · {card.artifact_count} {tr("图片", "images")}
                    </span>
                  </div>
                  <CardStatusTag status={card.status} tr={tr} />
                  <div className="fw-kc-actions">
                    <button
                      type="button"
                      className="fw-ghost-button"
                      onClick={() => onReview(card.card_id)}
                      disabled={Boolean(busy[`review:${card.card_id}`])}
                      data-testid={`overview-review-${card.card_id}`}
                    >
                      {tr("审核", "Review")}
                    </button>
                    {actions.canDiscard ? (
                      <button
                        type="button"
                        className="fw-ghost-button fw-danger"
                        onClick={() => onDiscard(card.card_id)}
                        disabled={Boolean(busy[`discard:${card.card_id}`])}
                        data-testid={`overview-discard-${card.card_id}`}
                      >
                        {tr("丢弃", "Discard")}
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </section>
  );
}

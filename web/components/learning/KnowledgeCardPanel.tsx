"use client";

import { FileText, Lock, Plus, ShieldAlert } from "lucide-react";
import type { KnowledgeCardView } from "@/lib/knowledge-card-api";
import { cardActions, generationSurface } from "./knowledgeCard";
import { StatusTag, type FwColor } from "./ui";
import type { TrFn } from "./locale";

/* ── shared status → label/color (used by panel + editors) ─────────────── */

export function cardStatusLabel(status: string, tr: TrFn): string {
  switch (status) {
    case "draft":
      return tr("待发布", "Pending draft");
    case "stale_evidence":
      return tr("证据已过期", "Stale evidence");
    case "publishing":
      return tr("发布中", "Publishing");
    case "published":
      return tr("已发布", "Published");
    case "publish_failed":
      return tr("发布失败", "Publish failed");
    case "reconcile_required":
      return tr("需要核对", "Reconcile required");
    case "retracting":
      return tr("撤回中", "Retracting");
    case "retract_reconcile_required":
      return tr("撤回需核对", "Retract reconcile");
    case "retracted":
      return tr("已撤回", "Retracted");
    case "discarded":
      return tr("已丢弃", "Discarded");
    default:
      return status;
  }
}

export function cardStatusColor(status: string): FwColor {
  switch (status) {
    case "published":
    case "retracted":
      return "blue";
    case "publish_failed":
    case "stale_evidence":
    case "retract_reconcile_required":
      return "coral";
    case "draft":
    case "reconcile_required":
    case "retracting":
    case "discarded":
      return "amber";
    case "publishing":
      return "blue";
    default:
      return "amber";
  }
}

export function CardStatusTag({ status, tr }: { status: string; tr: TrFn }) {
  return (
    <StatusTag color={cardStatusColor(status)}>{cardStatusLabel(status, tr)}</StatusTag>
  );
}

/** Non-blocking pending summary shown in the Evidence Panel (§13.5). */
export function KnowledgeCardPanel({
  cards,
  kpId,
  stableMastery,
  tr,
  busy,
  onReview,
  onDiscard,
  onCreate,
}: {
  cards: KnowledgeCardView[];
  kpId: string;
  stableMastery: boolean;
  tr: TrFn;
  busy: Record<string, boolean>;
  onReview: (cardId: string) => void;
  onDiscard: (cardId: string) => void;
  onCreate: () => void;
}) {
  const card =
    cards.find((c) => c.knowledge_point_id === kpId && c.status !== "discarded") ?? null;

  if (!card) {
    if (!stableMastery) return null;
    return (
      <div className="fw-kc-summary" data-testid="knowledge-card-panel">
        <div className="fw-kc-summary-head">
          <strong className="flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5 text-[var(--fw-amber)]" />
            {tr("知识卡片", "Knowledge card")}
          </strong>
          <StatusTag color="amber">{tr("可沉淀", "ready")}</StatusTag>
        </div>
        <p className="text-sm text-[var(--fw-muted)]">
          {tr(
            "该知识点已稳定掌握，可以沉淀一张知识卡片。",
            "This point has stable mastery — you can create a knowledge card.",
          )}
        </p>
        <button
          type="button"
          className="fw-ghost-button"
          onClick={onCreate}
          disabled={Boolean(busy.ensure)}
          data-testid="create-knowledge-card"
        >
          <Plus className="h-4 w-4" />
          {tr("新建草稿", "Create draft")}
        </button>
      </div>
    );
  }

  const actions = cardActions(card);
  const generation = generationSurface(card);
  const metaBits = [
    `${card.source_count} ${tr("来源", "sources")}`,
    `${card.evidence_count} ${tr("证据", "evidence")}`,
    `${card.artifact_count} ${tr("图片", "images")}`,
  ];
  const metaLine = card.status === "published"
    ? `${metaBits.join(" · ")} · ${tr("已写入", "in KB")} ${card.target_kb_name ?? "—"}`
    : card.status === "publish_failed"
      ? `${metaBits.join(" · ")} · ${tr("草稿已保留", "draft retained")}`
      : `${metaBits.join(" · ")} · ${tr("尚未写入 KB", "not in KB yet")}`;

  return (
    <div className="fw-kc-summary" data-testid="knowledge-card-panel">
      <div className="fw-kc-summary-head">
        <strong className="flex items-center gap-1.5">
          <FileText className="h-3.5 w-3.5 text-[var(--fw-amber)]" />
          {tr("知识卡片草稿", "Knowledge card draft")}
        </strong>
        <CardStatusTag status={card.status} tr={tr} />
      </div>

      {card.status === "stale_evidence" ? (
        <div className="fw-kc-note coral" data-testid="stale-evidence-note">
          <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
          <span>
            {tr(
              "需要新的稳定掌握证据：绑定证据已被推翻，卡片只读。",
              "New stable evidence required: the bound assessment was overturned, so the card is read-only.",
            )}
          </span>
        </div>
      ) : card.status === "publish_failed" ? (
        <div className="fw-kc-note coral" data-testid="publish-failed-note">
          <span>
            <strong>{tr("发布失败 · 草稿已保留", "Publish failed · draft retained")}</strong>
            {" "}
            {tr(
              "重试不会创建重复文档，稳定掌握不受影响。",
              "Retry will not create a duplicate document; stable mastery is unaffected.",
            )}
          </span>
        </div>
      ) : null}

      <h4 className="fw-kc-title">{card.title || tr("（未命名草稿）", "(untitled draft)")}</h4>
      <p className="fw-kc-summary-text">
        {card.body || tr("暂无正文，可打开审核后编辑。", "No body yet — open Review to edit.")}
      </p>
      <div className="fw-kc-meta">{metaLine}</div>

      <div className="fw-kc-actions">
        <button
          type="button"
          className="fw-ghost-button"
          onClick={() => onReview(card.card_id)}
          disabled={Boolean(busy[`review:${card.card_id}`])}
          data-testid={`review-card-${card.card_id}`}
        >
          {tr("审核", "Review")}
        </button>
        {actions.canDiscard ? (
          <button
            type="button"
            className="fw-ghost-button fw-danger"
            onClick={() => onDiscard(card.card_id)}
            disabled={Boolean(busy[`discard:${card.card_id}`])}
            data-testid={`discard-card-${card.card_id}`}
          >
            <Lock className="h-3.5 w-3.5" />
            {tr("丢弃", "Discard")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

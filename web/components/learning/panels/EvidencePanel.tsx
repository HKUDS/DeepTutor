"use client";

import { CalendarClock, ShieldCheck, Swords } from "lucide-react";
import type { AttemptDetail } from "@/lib/feynman-learning";
import type { KnowledgeCardView } from "@/lib/knowledge-card-api";
import {
  activeGaps,
  masteryDisplay,
  protocolLabel,
  rubricRows,
} from "../contract";
import { KnowledgeCardPanel } from "../KnowledgeCardPanel";
import { ModelIdentityBlock, type TeachingModelInfo } from "../ModelIdentity";
import { SectionHead, StatusTag } from "../ui";
import type { TrFn } from "../locale";

const RUBRIC_VERDICT: Record<string, { cn: string; en: string; color: "green" | "amber" | "coral" | "blue" }> = {
  pass: { cn: "通过", en: "Pass", color: "green" },
  partial: { cn: "部分", en: "Partial", color: "amber" },
  fail: { cn: "未达标", en: "Fail", color: "coral" },
  unset: { cn: "未评分", en: "Unscored", color: "blue" },
};

function rubricLabel(key: string, tr: TrFn): string {
  switch (key) {
    case "rubric.correctness":
      return tr("通俗准确", "Correctness");
    case "rubric.completeness":
      return tr("核心完整", "Completeness");
    case "rubric.causalClarity":
      return tr("因果清晰", "Causal clarity");
    case "rubric.transfer":
      return tr("新情境迁移", "Transfer");
    default:
      return key;
  }
}

export function EvidencePanel({
  attempt,
  teaching,
  tr,
  onChallenge,
  busy,
  cards,
  kpId,
  onReviewCard,
  onDiscardCard,
  onCreateCard,
}: {
  attempt: AttemptDetail | null;
  teaching: TeachingModelInfo | null;
  tr: TrFn;
  onChallenge: (mode: "reassess_existing" | "collect_new_evidence") => void;
  busy: Record<string, boolean>;
  cards: KnowledgeCardView[];
  kpId: string;
  onReviewCard: (cardId: string) => void;
  onDiscardCard: (cardId: string) => void;
  onCreateCard: () => void;
}) {
  const projection = attempt?.projection ?? null;
  const mastery = masteryDisplay(projection);
  const latest = attempt?.assessments[attempt.assessments.length - 1] ?? null;
  const gate = latest?.server_gate_result ?? null;
  const passed = gate?.passed ?? false;
  const rows = rubricRows(latest);
  const gaps = activeGaps(attempt?.gaps ?? []);
  const citedSources = latest?.source_citations ?? attempt?.evidence.flatMap((e) => e.source_citations) ?? [];
  const sourcesById = new Map(
    citedSources.map((c, i) => [c.source_snapshot_id, i + 1]),
  );

  const stageSummary =
    mastery.masteryState === "provisional_mastery"
      ? tr(
          "本轮只算暂时掌握：进入延迟复教队列，再次通过后才显示稳定掌握。",
          "This round counts as provisional only — it enters the delayed-reteach queue and becomes stable after a second pass.",
        )
      : mastery.masteryState === "stable_mastery"
        ? tr(
            "延迟复教已通过，已写入稳定掌握。",
            "Delayed reteach passed — stable mastery recorded.",
          )
        : mastery.masteryState === "needs_revision"
          ? tr(
              "本轮未通过：记录缺口，回到学习中重新形成证据。",
              "Gate not passed this round: gaps recorded, return to the learning loop.",
            )
          : tr(
              "本轮通过只算暂时掌握，不会直接写入稳定掌握。",
              "Passing this round only grants provisional mastery — never stable directly.",
            );

  return (
    <aside className="fw-panel fw-evidence-panel" data-testid="evidence-panel">
      <div className="fw-panel-head">
        <div className="fw-panel-title">
          <strong>{tr("本轮证据", "Evidence")}</strong>
          <span className="text-xs text-[var(--fw-muted)]">
            {tr("服务端 Evidence Gate", "Server Evidence Gate")}
          </span>
        </div>
        <StatusTag color={passed ? "green" : "coral"}>
          {passed ? tr("已达标", "Gate passed") : tr("未达标", "Gate open")}
        </StatusTag>
      </div>

      <div className="fw-panel-scroll">
        <div className="fw-evidence-content">
          {/* Hard gate summary */}
          <div className="fw-gate-summary" data-testid="gate-summary">
            <strong>
              {passed
                ? tr("■ 硬门禁已通过", "■ Hard gate passed")
                : tr("■ 硬门禁未通过", "■ Hard gate not passed")}
            </strong>
            {gate ? (
              <span className="text-sm">
                {gate.reasons.length > 0
                  ? gate.reasons.join("；")
                  : passed
                    ? tr(
                        "追问、迁移与帮助约束完成后，服务端已写入暂时掌握。",
                        "Evidence, probes, transfer and help constraints satisfied — provisional mastery written.",
                      )
                    : tr(
                        "追问、迁移与帮助约束完成后，服务端才允许写入暂时掌握。",
                        "Probes, transfer and help constraints must complete before the server writes provisional mastery.",
                      )}
              </span>
            ) : (
              <span className="text-sm">
                {tr(
                  "证据链尚不完整，服务端计算门禁。",
                  "Evidence chain incomplete — the server computes the gate.",
                )}
              </span>
            )}
            {gate && gate.blocked_by_conflict.length > 0 ? (
              <span className="text-sm text-[var(--fw-coral)]">
                {tr("受来源冲突阻塞：", "Blocked by source conflict: ")}
                {gate.blocked_by_conflict.join("，")}
              </span>
            ) : null}
          </div>

          {/* Fixed rubric */}
          <div data-testid="rubric-list">
            <SectionHead
              label={tr("固定 Rubric", "Fixed rubric")}
              trailing={<StatusTag color="amber">{tr("模型评分", "model scored")}</StatusTag>}
            />
            <div className="fw-rubric">
              {rows.map((row) => {
                const v = RUBRIC_VERDICT[row.verdictKey];
                return (
                  <div key={row.key} className="fw-rubric-row">
                    <span className="text-sm">{rubricLabel(row.labelKey, tr)}</span>
                    <StatusTag color={v.color}>
                      {tr(v.cn, v.en)} · {row.score}
                    </StatusTag>
                  </div>
                );
              })}
            </div>
            <span className="text-xs text-[var(--fw-muted)]">
              {tr(
                "评分可质疑并触发重评，不能手动改为掌握。",
                "Scores can be challenged for reassessment; mastery can never be set manually.",
              )}
            </span>
          </div>

          {/* Challenge */}
          <div className="flex flex-wrap gap-2" data-testid="challenge-actions">
            <button
              type="button"
              className="fw-ghost-button"
              onClick={() => onChallenge("reassess_existing")}
              disabled={busy.challenge || !latest}
              data-testid="challenge-reassess"
            >
              <Swords className="h-4 w-4" />
              {tr("质疑重评", "Challenge")}
            </button>
            <button
              type="button"
              className="fw-ghost-button"
              onClick={() => onChallenge("collect_new_evidence")}
              disabled={busy.challenge}
            >
              <Swords className="h-4 w-4" />
              {tr("重新收集证据", "Collect new evidence")}
            </button>
          </div>

          {/* Cited sources */}
          <div data-testid="cited-sources">
            <SectionHead
              label={tr("来源引用", "Cited sources")}
              trailing={<StatusTag color="violet">{tr("可追溯", "traceable")}</StatusTag>}
            />
            <div className="fw-source-list">
              {citedSources.length === 0 ? (
                <span className="text-sm text-[var(--fw-muted)]">
                  {tr("尚无引用", "No citations yet")}
                </span>
              ) : (
                citedSources.map((c, i) => (
                  <div key={`${c.source_snapshot_id}-${i}`} className="fw-source-row">
                    <span className="fw-source-mark">[{sourcesById.get(c.source_snapshot_id) ?? "?"}]</span>
                    <div className="min-w-0 text-sm">
                      {c.source_snapshot_id}
                      {c.anchor ? <span className="text-[var(--fw-muted)]"> · {c.anchor}</span> : null}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Gaps */}
          <div data-testid="gap-list">
            <SectionHead
              label={<span className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-[var(--fw-coral)]" />{tr("当前缺口", "Current gaps")}</span>}
            />
            <div className="grid gap-1.5">
              {gaps.length === 0 ? (
                <span className="text-sm text-[var(--fw-muted)]">
                  {tr("暂无缺口", "No gaps recorded")}
                </span>
              ) : (
                gaps.map((g) => (
                  <div key={g.id} className="fw-note coral text-sm">
                    <strong>{g.label || g.description}</strong>
                    {g.priority > 0 ? (
                      <span className="text-xs text-[var(--fw-muted)]">
                        {tr("优先级", "priority")} {g.priority}
                      </span>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Help level */}
          <div className="fw-note amber" data-testid="help-level">
            <strong>
              {tr("Help level", "Help level")}：{attempt?.attempt.max_help_level ?? tr("无", "none")}
            </strong>
            <span className="text-sm text-[var(--fw-muted)]">
              {attempt?.attempt.max_help_level === "full_explanation"
                ? tr("已使用完整讲解，需要重新复教。", "Full explanation used — reteach required.")
                : tr("未使用完整讲解。", "Full explanation not used.")}
            </span>
          </div>

          {/* Review timing state */}
          <div className="fw-note" data-testid="mastery-note">
            <div className="flex items-center gap-2">
              <CalendarClock className="h-4 w-4 shrink-0 text-[var(--fw-green)]" />
              <strong>{tr("掌握与复习", "Mastery & review")}</strong>
            </div>
            <span className="text-sm">{stageSummary}</span>
            {mastery.nextReviewAt ? (
              <span className="text-xs text-[var(--fw-muted)]">
                {tr("下次复教", "Next review")}:{" "}
                {new Date(mastery.nextReviewAt * 1000).toLocaleString()}
              </span>
            ) : null}
          </div>

          {/* Model identity (frozen evaluator) */}
          <ModelIdentityBlock teaching={teaching} evaluator={attempt?.attempt.evaluator_snapshot ?? null} tr={tr} />

          {/* Latest assessment revision */}
          {latest ? (
            <div className="fw-block fw-blue text-xs" data-testid="assessment-revision">
              {`${tr("评估", "Assessment")} #${latest.assessment_sequence} · rev ${latest.revision}`}
              {latest.model_invocation_id ? (
                <>
                  {" · "}
                  {tr("invocation", "invocation")}{" "}
                  {latest.model_invocation_id.slice(0, 8)}
                </>
              ) : null}
              {latest.evaluator_snapshot ? (
                <>
                  {" · "}
                  {protocolLabel(
                    latest.evaluator_snapshot.resolved_api_protocol ||
                      latest.evaluator_snapshot.requested_api_protocol,
                  )}
                </>
              ) : null}
            </div>
          ) : null}

          {/* Knowledge-card pending summary (non-blocking, §13.5) */}
          <KnowledgeCardPanel
            cards={cards}
            kpId={kpId}
            stableMastery={mastery.masteryState === "stable_mastery"}
            tr={tr}
            busy={busy}
            onReview={onReviewCard}
            onDiscard={onDiscardCard}
            onCreate={onCreateCard}
          />
        </div>
      </div>
    </aside>
  );
}

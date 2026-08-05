"use client";

import type { StageState, MasteryDisplay } from "./contract";
import { StatusTag } from "./ui";
import type { TrFn } from "./locale";

const STAGE_META: Record<
  StageState["key"],
  { cn: string; en: string; color: "green" | "amber" | "coral" }
> = {
  explain: { cn: "讲解", en: "Explain", color: "green" },
  probe: { cn: "追问", en: "Probe", color: "amber" },
  transfer: { cn: "迁移", en: "Transfer", color: "coral" },
  feedback: { cn: "反馈", en: "Feedback", color: "amber" },
};

export function stageTitle(key: StageState["key"], tr: TrFn): string {
  return tr(STAGE_META[key].cn, STAGE_META[key].en);
}

/** Mastery state chip text + tone (§6.2). */
export function masteryStatusChip(m: MasteryDisplay, tr: TrFn) {
  switch (m.masteryState) {
    case "provisional_mastery":
      return tr("暂时掌握 · 待延迟复教", "Provisional · reteach due");
    case "stable_mastery":
      return tr("稳定掌握", "Stable mastery");
    case "needs_revision":
      return tr("待修订", "Needs revision");
    case "in_progress":
      return tr("本轮学习中", "Learning in progress");
    default:
      return tr("待学习", "Not started");
  }
}

function masteryColor(m: MasteryDisplay): "green" | "amber" | "coral" | "blue" {
  switch (m.tone) {
    case "stable":
      return "green";
    case "provisional":
      return "blue";
    case "revision":
      return "coral";
    case "in-progress":
      return "amber";
    default:
      return "blue";
  }
}

export function StageBar({
  stages,
  mastery,
  tr,
}: {
  stages: StageState[];
  mastery: MasteryDisplay;
  tr: TrFn;
}) {
  return (
    <div className="fw-concept-head">
      <div className="fw-concept-row">
        <div className="fw-panel-title">
          <span className="text-xs text-[var(--fw-muted)]">
            {tr("当前阶段", "Current stage")}
          </span>
          <StatusTag color={masteryColor(mastery)}>
            {masteryStatusChip(mastery, tr)}
          </StatusTag>
        </div>
        <span className="shrink-0 text-xs text-[var(--fw-muted)]">
          {tr("讲解 → 追问 → 迁移 → 反馈", "Explain → Probe → Transfer → Feedback")}
        </span>
      </div>

      <div className="fw-stage-track" role="list" aria-label={tr("学习阶段进度", "Stage progress")}>
        {stages.map((stage) => {
          const meta = STAGE_META[stage.key];
          const stateText =
            stage.status === "done"
              ? tr("已记录", "done")
              : stage.status === "active"
                ? tr("进行中", "in progress")
                : stage.status === "blocked"
                  ? tr("需重新复教", "reteach")
                  : tr("未开始", "not started");
          return (
            <div
              key={stage.key}
              className={`fw-stage fw-${meta.color} ${stage.status}`}
              role="listitem"
              data-stage={stage.key}
              data-status={stage.status}
            >
              <strong>{stageTitle(stage.key, tr)}</strong>
              <small>
                {stateText}
                {stage.count ? ` · ${stage.count}` : ""}
              </small>
            </div>
          );
        })}
      </div>
    </div>
  );
}

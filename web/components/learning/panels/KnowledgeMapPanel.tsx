"use client";

import {
  Flag,
  GitBranch,
  Pencil,
  RotateCw,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import type {
  FeynmanMapPayload,
  GapRecord,
  KnowledgeProjection,
  SourceConflict,
  SourceSnapshot,
} from "@/lib/feynman-learning";
import { activeGaps } from "../contract";
import { LongId } from "../LongId";
import { SectionHead, StatusTag, type FwColor } from "../ui";
import type { TrFn } from "../locale";

export interface KpRow {
  id: string;
  name: string;
  type: string;
  status: string;
  mastery: number;
  projection: KnowledgeProjection | null;
  isActive: boolean;
  color: FwColor;
  subtitle: string;
}

const KP_STATUS_META: Record<
  string,
  { cn: string; en: string; color: FwColor }
> = {
  mastered: { cn: "已掌握", en: "Mastered", color: "green" },
  learning: { cn: "学习中", en: "Learning", color: "amber" },
  new: { cn: "未开始", en: "Not started", color: "blue" },
};

export function kpRows(
  payload: FeynmanMapPayload,
  selected: string,
): KpRow[] {
  const rows: KpRow[] = [];
  for (const mod of payload.map.modules) {
    for (const kp of mod.knowledge_points) {
      const projection = payload.projections[kp.id] ?? null;
      const meta = KP_STATUS_META[kp.status] ?? KP_STATUS_META.new;
      let subtitle = meta.cn;
      if (projection?.mastery_state === "provisional_mastery")
        subtitle = "暂时掌握 · 待复教";
      else if (projection?.mastery_state === "stable_mastery")
        subtitle = "稳定掌握";
      else if (projection?.mastery_state === "needs_revision")
        subtitle = "待修订";
      else if (kp.status === "new") subtitle = "待学习";
      rows.push({
        id: kp.id,
        name: kp.name,
        type: kp.type,
        status: kp.status,
        mastery: kp.mastery,
        projection,
        isActive: kp.id === selected,
        color: meta.color,
        subtitle,
      });
    }
  }
  return rows;
}

export function KnowledgeMapPanel({
  payload,
  selectedKpId,
  conflicts,
  gapRecords,
  tr,
  onSelectKp,
  onStartResume,
  onTestSkip,
  onConfirmMap,
  onEditGoal,
  busy,
}: {
  payload: FeynmanMapPayload;
  selectedKpId: string;
  conflicts: SourceConflict[];
  gapRecords: GapRecord[];
  tr: TrFn;
  onSelectKp: (kpId: string) => void;
  onStartResume: () => void;
  onTestSkip: () => void;
  onConfirmMap: () => void;
  onEditGoal: () => void;
  busy: Record<string, boolean>;
}) {
  const rows = kpRows(payload, selectedKpId);
  const next = payload.next;
  const selected = rows.find((r) => r.id === selectedKpId);
  const openConflictCount = conflicts.filter((c) => c.status === "open").length;
  const sources = payload.source_snapshots;
  const gaps = activeGaps(gapRecords);
  const dueReviews = payload.map.due_reviews;
  const needsConfirm = payload.map_version > 0;

  const todayNodes = rows.filter((r) => r.projection || r.id === selectedKpId);
  const laterNodes = rows.filter((r) => !r.projection && r.id !== selectedKpId);

  return (
    <aside className="fw-panel fw-map-panel" data-testid="map-panel">
      <div className="fw-panel-head">
        <div className="fw-panel-title">
          <strong>{tr("知识地图", "Knowledge map")}</strong>
          <span className="text-xs text-[var(--fw-muted)]">
            {tr("今日", "Today")} {todayNodes.length}
            {tr(" 个节点", " nodes")}
          </span>
        </div>
        <button
          type="button"
          className="fw-icon-button"
          aria-label={tr("编辑学习目标", "Edit learning goal")}
          title={tr("编辑学习目标", "Edit learning goal")}
          onClick={onEditGoal}
        >
          <Pencil className="h-4 w-4" />
        </button>
      </div>

      <div className="fw-panel-scroll">
        <div className="fw-content">
          {/* Goal notes */}
          <div className="fw-block fw-blue">
            <span className="text-xs text-[var(--fw-muted)]">
              {tr("当前目标", "Current goal")}
            </span>
            <strong className="block pt-1">
              {selected?.name || next.knowledge_point_name || tr("选择知识点", "Select a knowledge point")}
            </strong>
            <span className="block pt-1 text-xs text-[var(--fw-muted)]">
              {next.reason || tr("已就绪", "Ready to learn")}
            </span>
            {dueReviews > 0 ? (
              <StatusTag color="coral" title={tr("有到期复习", "Due reviews")}>
                {dueReviews} {tr("项待复习", "due for review")}
              </StatusTag>
            ) : null}
          </div>

          {/* Actions */}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="fw-primary-button"
              onClick={onStartResume}
              disabled={busy.resume}
              data-testid="feynman-start-resume"
            >
              <RotateCw className="h-4 w-4" />
              {busy.resume
                ? tr("恢复中…", "Resuming…")
                : selected?.projection?.active_attempt_id
                  ? tr("继续本轮", "Resume attempt")
                  : tr("开始本轮", "Start attempt")}
            </button>
            <button
              type="button"
              className="fw-ghost-button"
              onClick={onTestSkip}
              data-testid="feynman-test-skip"
            >
              <Sparkles className="h-4 w-4" />
              {tr("测试跳过", "Test skip")}
            </button>
          </div>

          {/* Conflicts — both sides visible, never collapsed */}
          {openConflictCount > 0 ? (
            <div className="fw-map-section" data-testid="conflict-list">
              <SectionHead
                label={
                  <span className="flex items-center gap-1.5">
                    <ShieldAlert className="h-3.5 w-3.5 text-[var(--fw-coral)]" />
                    {tr("来源冲突", "Source conflicts")}
                  </span>
                }
                trailing={<StatusTag color="coral">{openConflictCount}</StatusTag>}
              />
              <div className="grid gap-2">
                {conflicts
                  .filter((c) => c.status === "open")
                  .map((conflict) => (
                    <ConflictSummary
                      key={conflict.id}
                      conflict={conflict}
                      sources={sources}
                      tr={tr}
                    />
                  ))}
              </div>
            </div>
          ) : null}

          {/* Today's nodes */}
          <div className="fw-map-section">
            <SectionHead
              label={tr("今日节点", "Today's nodes")}
              trailing={<span className="text-xs">{tr("优先级", "Priority")}</span>}
            />
            <div className="fw-node-list">
              {todayNodes.length === 0 ? (
                <span className="text-xs text-[var(--fw-muted)]">
                  {tr("还没有进行中的知识点", "No active knowledge points yet.")}
                </span>
              ) : (
                todayNodes.map((row) => <NodeButton key={row.id} row={row} onSelect={() => onSelectKp(row.id)} />)
              )}
            </div>
          </div>

          {/* Later nodes */}
          {laterNodes.length > 0 ? (
            <div className="fw-map-section">
              <SectionHead label={tr("后续", "Later")} trailing={<span className="text-xs">{tr("状态", "Status")}</span>} />
              <div className="fw-node-list">
                {laterNodes.map((row) => <NodeButton key={row.id} row={row} onSelect={() => onSelectKp(row.id)} />)}
              </div>
            </div>
          ) : null}

          {/* Source provenance */}
          <div className="fw-map-section" data-testid="source-list">
            <SectionHead
              label={tr("资料来源", "Sources")}
              trailing={<StatusTag color="violet">{sources.length}</StatusTag>}
            />
            <div className="grid gap-1">
              {sources.length === 0 ? (
                <span className="text-xs text-[var(--fw-muted)]">
                  {tr("还没有物化来源快照", "No materialized source snapshots yet.")}
                </span>
              ) : (
                sources.map((s, idx) => (
                  <div key={s.id} className="fw-source-row">
                    <span className="fw-source-mark">
                      {s.source_type === "web" ? "[W]" : `[${idx + 1}]`}
                    </span>
                    <div className="min-w-0">
                      <div className="truncate">{s.title || s.locator || s.id}</div>
                      <LongId value={s.id} maxChars={14} tr={tr} />
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Prerequisite/related relations from the confirmed map version */}
          <RelationsPanel payload={payload} tr={tr} />

          {/* New version confirmation */}
          {needsConfirm ? (
            <div className="fw-block fw-blue" data-testid="map-confirm">
              <div className="flex items-center gap-2">
                <Flag className="h-4 w-4 shrink-0 text-[var(--fw-blue)]" />
                <strong>{tr("新地图版本", "New map version")}</strong>
              </div>
              <span className="block pt-1 text-xs text-[var(--fw-muted)]">
                {tr(
                  "当前版本 v",
                  "Current version v",
                )}
                {payload.map_version} ·
                {tr(
                  "确认后绑定到新的来源快照，进行中的不兼容尝试将失效。",
                  "confirming freezes source snapshots and invalidates incompatible attempts.",
                )}
              </span>
              <button
                type="button"
                className="fw-ghost-button mt-2"
                onClick={onConfirmMap}
                data-testid="feynman-confirm-map"
              >
                {tr("确认此版本", "Confirm this version")}
              </button>
            </div>
          ) : null}

          {/* Gaps for the selected point */}
          {gaps.length > 0 ? (
            <div className="fw-map-section" data-testid="map-gaps">
              <SectionHead
                label={<span className="flex items-center gap-1.5"><ShieldAlert className="h-3.5 w-3.5 text-[var(--fw-coral)]" />{tr("关联缺口", "Related gaps")}</span>}
              />
              <div className="grid gap-1">
                {gaps.map((g) => (
                  <div key={g.id} className="fw-block fw-coral text-sm">
                    {g.label || g.description}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  );
}

function NodeButton({
  row,
  onSelect,
}: {
  row: KpRow;
  onSelect: () => void;
}) {
  const marker =
    row.status === "mastered" ? "✓" : row.status === "learning" ? "!" : "•";
  return (
    <button
      type="button"
      className={`fw-node fw-${row.color}${row.isActive ? " current" : ""}`}
      onClick={onSelect}
      aria-current={row.isActive ? "true" : undefined}
      data-testid="map-node"
    >
      <span className="fw-node-mark">{marker}</span>
      <span className="fw-node-body">
        <strong>{row.name}</strong>
        <small>{row.subtitle}</small>
      </span>
      <span className="fw-priority">
        {row.isActive ? "P1" : row.projection ? "P2" : "P3"}
      </span>
    </button>
  );
}

function ConflictSummary({
  conflict,
  sources,
  tr,
}: {
  conflict: SourceConflict;
  sources: SourceSnapshot[];
  tr: TrFn;
}) {
  const byId = new Map(sources.map((s) => [s.id, s]));
  return (
    <div className="fw-conflict" data-testid="conflict-card">
      <div>
        <strong className="text-sm">{tr("冲突", "Conflict")}：{conflict.claim}</strong>
      </div>
      <div className="fw-conflict-sides">
        {conflict.source_snapshot_ids.map((id) => {
          const s = byId.get(id);
          if (!s) return null;
          return (
            <div key={id} className="fw-conflict-side">
              <div className="text-xs text-[var(--fw-muted)]">
                {s.source_type === "web" ? tr("外部补充", "Web") : tr("个人资料", "Material")}
              </div>
              <div className="text-sm">{s.title || s.locator || s.id}</div>
              <LongId value={s.id} maxChars={12} tr={tr} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RelationsPanel({
  payload,
  tr,
}: {
  payload: FeynmanMapPayload;
  tr: TrFn;
}) {
  const version = payload.map_versions[payload.map_versions.length - 1];
  const edges = version?.edges ?? [];
  if (!edges.length) return null;
  const names = new Map<string, string>();
  for (const mod of payload.map.modules) {
    for (const kp of mod.knowledge_points) names.set(kp.id, kp.name);
  }
  return (
    <div className="fw-map-section" data-testid="relation-list">
      <SectionHead
        label={<span className="flex items-center gap-1.5"><GitBranch className="h-3.5 w-3.5" />{tr("前置 / 关联", "Prerequisite / related")}</span>}
      />
      <div className="grid gap-1">
        {edges.map((edge, idx) => {
          const from = names.get(String(edge.from ?? edge.source ?? "")) ?? String(edge.from ?? edge.source ?? "");
          const to = names.get(String(edge.to ?? edge.target ?? "")) ?? String(edge.to ?? edge.target ?? "");
          if (!from && !to) return null;
          return (
            <div key={idx} className="fw-block text-xs">
              {from} → {to}
            </div>
          );
        })}
      </div>
    </div>
  );
}

"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import type { TrFn } from "./locale";

export type FwColor = "blue" | "green" | "amber" | "coral" | "violet";

export const FW_COLOR_CLASS: Record<FwColor, string> = {
  blue: "fw-blue",
  green: "fw-green",
  amber: "fw-amber",
  coral: "fw-coral",
  violet: "fw-violet",
};

/** Small bordered status tag with the approved color semantics. */
export function StatusTag({
  color,
  children,
  title,
}: {
  color: FwColor;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`fw-tag ${FW_COLOR_CLASS[color]}`} title={title}>
      {children}
    </span>
  );
}

/** Section label row used across all three panels. */
export function SectionHead({
  label,
  trailing,
}: {
  label: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <div className="fw-section-label">
      <span className="min-w-0 overflow-wrap-anywhere">{label}</span>
      {trailing ? <span className="shrink-0">{trailing}</span> : null}
    </div>
  );
}

export function LoadingState({ tr }: { tr: TrFn }) {
  return (
    <div className="fw-empty" role="status" data-testid="feynman-loading">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span>{tr("加载学习中…", "Loading workspace…")}</span>
    </div>
  );
}

export function EmptyPathState({ tr }: { tr: TrFn }) {
  return (
    <div className="fw-empty" data-testid="feynman-empty-path">
      <strong>{tr("这条路径还没有知识点", "This path has no knowledge points yet.")}</strong>
      <span>
        {tr(
          "先在「对话」中用 Mastery Path 模式建立知识地图。",
          "Build a knowledge map first from Chat in Mastery Path mode.",
        )}
      </span>
    </div>
  );
}

/** Recoverable optimistic-concurrency / idempotency conflict (§8.3). */
export function RecoverableErrorBanner({
  message,
  tr,
  onRefresh,
}: {
  message: string;
  tr: TrFn;
  onRefresh: () => void;
}) {
  return (
    <div className="fw-banner" role="alert" data-testid="feynman-recoverable-error">
      <div className="min-w-0">
        <strong>{tr("状态已变化", "State changed")}</strong>
        <div className="text-sm opacity-90">{message}</div>
        <div className="text-xs opacity-75">
          {tr(
            "另一个窗口可能已修改。刷新后重试，不会覆盖对方的修改。",
            "Another tab may have changed this. Refresh and retry — edits are never silently overwritten.",
          )}
        </div>
      </div>
      <button
        type="button"
        className="fw-ghost-button shrink-0"
        onClick={onRefresh}
        data-testid="feynman-recover-refresh"
      >
        {tr("刷新", "Refresh")}
      </button>
    </div>
  );
}

export function FatalErrorState({ message, tr }: { message: string; tr: TrFn }) {
  return (
    <div className="fw-empty" data-testid="feynman-fatal-error">
      <strong>{tr("无法加载学习工作台", "Could not load the learning workspace")}</strong>
      <span className="text-sm">{message}</span>
    </div>
  );
}

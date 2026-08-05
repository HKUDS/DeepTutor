"use client";

import { useCallback, useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { AlertTriangle, X } from "lucide-react";
import type { TrFn } from "./locale";
import type { CardConfirmation } from "./knowledgeCardReducer";

/**
 * Accessible explicit-confirmation dialog (§13.5) — never ``window.confirm``.
 * Publishes name the target KB and explain the card becomes searchable;
 * retraction likewise explains the irreversible KB removal; discard explains
 * the draft is removed without touching learning evidence.
 *
 * Round-1 accessibility contract:
 * - Initial focus goes to the primary (confirm) action.
 * - Tab / Shift+Tab cycle through the dialog's focusable elements only.
 * - Escape cancels, but only when the confirmed mutation is not busy — closing
 *   while the mutation is still in flight would leave a misleading UI state.
 * - Focus is restored to the exact previously-focused trigger element on every
 *   close/unmount path (confirm, cancel, Escape, backdrop close button).
 */
export function KnowledgeCardDialog({
  confirm,
  tr,
  busy,
  onConfirm,
  onCancel,
}: {
  confirm: CardConfirmation;
  tr: TrFn;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Remember the exact trigger that opened the dialog so focus can be
    // restored when it closes on any path (the cleanup runs on unmount).
    const previouslyFocused = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    return () => {
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        previouslyFocused.focus();
      }
    };
  }, []);

  /** The dialog's currently enabled focusable elements in document order. */
  const focusableElements = useCallback((): HTMLElement[] => {
    const root = dialogRef.current;
    if (!root) return [];
    return Array.from(
      root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => el.offsetParent !== null || el === document.activeElement);
  }, []);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      // Never close while the confirmed mutation is busy — the mutation keeps
      // running and closing would look like a cancel that did not cancel.
      if (!busy) onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableElements();
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (event.shiftKey) {
      if (active === first || (active && !dialogRef.current?.contains(active))) {
        event.preventDefault();
        last.focus();
      }
    } else if (active === last || (active && !dialogRef.current?.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  };

  const title =
    confirm.kind === "publish"
      ? tr("确认发布到知识库", "Confirm publish to knowledge base")
      : confirm.kind === "retract"
        ? tr("确认撤回已发布卡片", "Confirm retract published card")
        : tr("确认丢弃草稿", "Confirm discard draft");

  const body = (): ReactNode => {
    if (confirm.kind === "publish") {
      return (
        <>
          <p>
            {tr(
              "发布后，这张卡片将写入所选本地知识库并成为可检索文档。",
              "After publishing, this card is written to the selected local knowledge base and becomes searchable.",
            )}
          </p>
          <p className="fw-kc-dialog-kb">
            <strong>{confirm.targetKbName ?? "—"}</strong>
          </p>
          <p className="text-sm text-[var(--fw-muted)]">
            {tr(
              "发布与评分/掌握状态完全正交，不会修改答案、评分或掌握结论。",
              "Publication is fully orthogonal to scoring and mastery — it never changes answers, scores, or mastery.",
            )}
          </p>
        </>
      );
    }
    if (confirm.kind === "retract") {
      return (
        <>
          <p>
            {tr(
              "撤回会从知识库移除该文档并重建索引；在新索引确认前不会显示“已撤回”。",
              "Retraction removes the document from the knowledge base and rebuilds the index; it is not shown as retracted until the new index is confirmed.",
            )}
          </p>
          <p className="text-sm text-[var(--fw-muted)]">
            {tr(
              "学习证据与掌握状态不受影响。",
              "Learning evidence and mastery are unaffected.",
            )}
          </p>
        </>
      );
    }
    return (
      <>
        <p>
          {tr(
            "丢弃会删除这张未发布草稿，不会回退答案、评分或掌握状态。",
            "Discarding deletes this unpublished draft without reverting answers, scores, or mastery.",
          )}
        </p>
        <p className="text-sm text-[var(--fw-muted)]">
          {tr(
            "该操作不可撤销。",
            "This action cannot be undone.",
          )}
        </p>
      </>
    );
  };

  return (
    <div
      className="fw-kc-dialog-backdrop"
      role="presentation"
      data-testid="knowledge-card-confirm"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fw-kc-dialog"
        onKeyDown={handleKeyDown}
      >
        <div className="fw-kc-dialog-head">
          <span className="fw-kc-dialog-icon" aria-hidden="true">
            <AlertTriangle className="h-4 w-4" />
          </span>
          <strong>{title}</strong>
          <button
            type="button"
            className="fw-icon-button h-8 w-8"
            aria-label={tr("关闭", "Close")}
            onClick={onCancel}
            disabled={busy}
            data-testid="dialog-close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="fw-kc-dialog-body">{body()}</div>
        <div className="fw-kc-dialog-actions">
          <button type="button" className="fw-ghost-button" onClick={onCancel} disabled={busy} data-testid="dialog-cancel">
            {tr("取消", "Cancel")}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={confirm.kind === "discard" ? "fw-primary-button fw-danger-button" : "fw-primary-button"}
            onClick={onConfirm}
            disabled={busy}
            data-testid="confirm-card-action"
          >
            {confirm.kind === "publish"
              ? tr("确认发布", "Publish")
              : confirm.kind === "retract"
                ? tr("确认撤回", "Retract")
                : tr("确认丢弃", "Discard")}
          </button>
        </div>
      </div>
    </div>
  );
}

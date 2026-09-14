"use client";

import { useEffect, useRef } from "react";
import { ArrowRight, Database, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  SixDimensionEvidenceKind,
  SixDimensionResult,
} from "@/lib/learning-api";

const DIMENSION_LABELS = {
  knowledge: { zh: "知识", en: "Knowledge" },
  procedure: { zh: "解题程序", en: "Procedure" },
  understanding: { zh: "理解", en: "Understanding" },
  transfer: { zh: "迁移", en: "Transfer" },
  retention: { zh: "保持", en: "Retention" },
  habit: { zh: "习惯", en: "Habit" },
} as const;

const EVIDENCE_LABELS: Record<
  SixDimensionEvidenceKind,
  { zh: string; en: string }
> = {
  attempt: { zh: "作答", en: "Attempt" },
  error: { zh: "错因", en: "Error" },
  review: { zh: "复习", en: "Review" },
  route_task: { zh: "路线任务", en: "Route task" },
};

interface SixDimensionEvidenceDrawerProps {
  open: boolean;
  dimension: SixDimensionResult | null;
  onClose: () => void;
}

export default function SixDimensionEvidenceDrawer({
  open,
  dimension,
  onClose,
}: SixDimensionEvidenceDrawerProps) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open || !dimension) return null;

  const tr = (cn: string, en: string) => (zh ? cn : en);
  const label = DIMENSION_LABELS[dimension.key];
  const scored = dimension.data_state === "scored";

  return (
    <div
      role="dialog"
      aria-label={tr(`${label.zh}维度证据`, `${label.en} evidence`)}
      className="fixed inset-0 z-40 flex justify-end bg-black/20"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <div className="flex h-full w-full max-w-md flex-col border-l border-[var(--border)] bg-[var(--card)] shadow-2xl">
        <header className="flex items-start gap-3 border-b border-[var(--border)] px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
              {tr("六维学习画像", "Six-dimension profile")}
            </p>
            <div className="mt-1 flex items-baseline gap-2">
              <h2 className="text-lg font-semibold text-[var(--foreground)]">
                {zh ? label.zh : label.en}
              </h2>
              <span
                className={`text-sm font-medium ${
                  scored
                    ? "text-[var(--primary)]"
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                {scored
                  ? `${Math.round(dimension.score ?? 0)} / 100`
                  : tr("证据不足", "Insufficient evidence")}
              </span>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label={tr("关闭证据抽屉", "Close evidence drawer")}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
          <section aria-labelledby="dimension-explanation">
            <h3
              id="dimension-explanation"
              className="text-sm font-semibold text-[var(--foreground)]"
            >
              {tr("评分口径", "How this is scored")}
            </h3>
            <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
              {dimension.explanation}
            </p>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-[var(--accent)] px-3 py-2.5">
                <p className="text-xs text-[var(--muted-foreground)]">
                  {tr("证据数", "Evidence")}
                </p>
                <p className="mt-0.5 text-base font-semibold text-[var(--foreground)]">
                  {dimension.evidence_count}
                </p>
              </div>
              <div className="rounded-lg bg-[var(--accent)] px-3 py-2.5">
                <p className="text-xs text-[var(--muted-foreground)]">
                  {tr("置信度", "Confidence")}
                </p>
                <p className="mt-0.5 text-base font-semibold text-[var(--foreground)]">
                  {Math.round(dimension.confidence * 100)}%
                </p>
              </div>
            </div>
          </section>

          <section aria-labelledby="dimension-evidence-list">
            <div className="flex items-center gap-2">
              <Database
                className="h-4 w-4 text-[var(--muted-foreground)]"
                aria-hidden="true"
              />
              <h3
                id="dimension-evidence-list"
                className="text-sm font-semibold text-[var(--foreground)]"
              >
                {tr("证据引用", "Evidence references")}
              </h3>
            </div>
            {dimension.evidence_refs.length > 0 ? (
              <ul className="mt-3 space-y-2">
                {dimension.evidence_refs.map((reference) => {
                  const kind = EVIDENCE_LABELS[reference.kind];
                  return (
                    <li
                      key={`${reference.kind}:${reference.id}`}
                      className="rounded-lg border border-[var(--border)] px-3 py-2.5"
                    >
                      <span className="inline-flex rounded-full bg-[var(--accent)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                        {zh ? kind.zh : kind.en}
                      </span>
                      <p className="mt-1.5 break-all font-mono text-xs text-[var(--foreground)]">
                        {reference.id}
                      </p>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="mt-3 rounded-lg border border-dashed border-[var(--border)] px-3 py-4 text-sm text-[var(--muted-foreground)]">
                {tr("尚无可回溯的证据 ID。", "No traceable evidence IDs yet.")}
              </p>
            )}
          </section>

          <section className="rounded-xl border border-[var(--primary)]/25 bg-[var(--primary)]/5 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--foreground)]">
              <ArrowRight
                className="h-4 w-4 text-[var(--primary)]"
                aria-hidden="true"
              />
              {tr("下一步", "Next action")}
            </div>
            <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
              {dimension.next_action}
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

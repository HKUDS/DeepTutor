"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BookOpen,
  Circle,
  CircleCheck,
  CircleDot,
  Loader2,
  MessageSquare,
} from "lucide-react";

import {
  fetchObjectiveReport,
  type BoardModule,
  type ObjectiveReport,
  type ObjectiveStatus,
} from "@/lib/learning-api";

import { ObjectiveDetail } from "./ObjectiveDetail";
import { formatRelative, knowledgeTypeLabel } from "./format";

const STATUS_BORDER: Record<ObjectiveStatus, string> = {
  mastered: "border-green-500/50",
  learning: "border-yellow-500/50",
  new: "border-[var(--border)]",
};

const STATUS_ICON: Record<ObjectiveStatus, React.ReactNode> = {
  mastered: <CircleCheck className="h-3.5 w-3.5 text-green-500" />,
  learning: <CircleDot className="h-3.5 w-3.5 text-yellow-500" />,
  new: <Circle className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />,
};

/**
 * The topic as a board: modules become columns and objectives become cards.
 *
 * The projection is read-only; opening a card still reads the same evidence
 * trail as the outline and starts the same Mastery Study surface.
 */
export function LearningBoard({
  pathId,
  modules,
  revision,
  zh,
  onStartTutoring,
}: {
  pathId: string;
  modules: BoardModule[];
  revision: number;
  zh: boolean;
  onStartTutoring: (knowledgePointName: string) => void;
}) {
  const { t } = useTranslation();
  const [openId, setOpenId] = useState<string | null>(null);
  const [report, setReport] = useState<ObjectiveReport | null>(null);
  const [reportError, setReportError] = useState(false);
  const loaded = openId !== null && report?.id === openId;

  useEffect(() => {
    if (!openId) return;
    const controller = new AbortController();
    fetchObjectiveReport(pathId, openId, { signal: controller.signal })
      .then((result) => {
        setReport(result);
        setReportError(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setReport(null);
        setReportError(true);
      });
    return () => controller.abort();
  }, [openId, pathId, revision]);

  const toggle = useCallback((id: string) => {
    setOpenId((current) => (current === id ? null : id));
    setReport(null);
    setReportError(false);
  }, []);

  return (
    <div className="flex gap-4 overflow-x-auto pb-2">
      {modules.map((module) => (
        <div
          key={module.id}
          className="flex w-64 shrink-0 flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 p-3"
        >
          <div className="flex items-center justify-between gap-2">
            <h3 className="min-w-0 truncate text-[13px] font-semibold text-[var(--foreground)]">
              {module.name}
            </h3>
            <span className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]">
              {module.mastered}/{module.total}
            </span>
          </div>

          {module.cards.map((card) => {
            const open = openId === card.id;
            return (
              <div key={card.id}>
                <button
                  type="button"
                  onClick={() => toggle(card.id)}
                  aria-expanded={open}
                  className={`w-full rounded-lg border bg-[var(--card)] p-3 text-left transition hover:bg-[var(--muted)]/60 ${STATUS_BORDER[card.status]}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[13px] leading-snug text-[var(--foreground)]">
                      {card.name}
                    </span>
                    {STATUS_ICON[card.status]}
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2 text-[11px]">
                    <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[var(--muted-foreground)]">
                      {knowledgeTypeLabel(card.type, t)}
                    </span>
                    <span className="shrink-0 tabular-nums text-[var(--muted-foreground)]">
                      {Math.round(card.mastery_level * 100)}%
                    </span>
                  </div>
                  {card.next_review_at && (
                    <div className="mt-1.5 flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
                      <BookOpen className="h-3 w-3" />
                      {t("Review")} {formatRelative(card.next_review_at, zh)}
                    </div>
                  )}
                </button>

                {open && (
                  <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
                    {loaded && report ? (
                      <>
                        <ObjectiveDetail report={report} zh={zh} />
                        <button
                          type="button"
                          onClick={() => onStartTutoring(card.name)}
                          className="mt-2 flex h-8 w-full items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-xs font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
                        >
                          <MessageSquare className="h-3.5 w-3.5" />
                          {t("Start tutoring")}
                        </button>
                      </>
                    ) : reportError ? (
                      <p className="py-3 text-center text-xs text-[var(--muted-foreground)]">
                        {t("Evidence could not be loaded")}
                      </p>
                    ) : (
                      <div className="flex items-center justify-center py-3 text-[var(--muted-foreground)]">
                        <Loader2 className="h-4 w-4 animate-spin" />
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

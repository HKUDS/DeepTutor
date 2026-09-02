"use client";

import { useCallback, useEffect, useState } from "react";
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
import { formatRelative, type Translate } from "./format";

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

const TYPE_LABEL: Record<string, { cn: string; en: string }> = {
  concept: { cn: "概念", en: "Concept" },
  procedure: { cn: "流程", en: "Procedure" },
  memory: { cn: "记忆", en: "Memory" },
  design: { cn: "设计", en: "Design" },
};

/**
 * Visual card-based learning board — modules as columns, objectives as cards.
 *
 * Clicking a card opens the same evidence trail the list view uses; a
 * "start tutoring" button navigates into a mastery chat pre-scoped to the
 * selected objective.
 */
export function LearningBoard({
  pathId,
  modules,
  revision,
  tr,
  zh,
  onStartTutoring,
}: {
  pathId: string;
  modules: BoardModule[];
  revision: number;
  tr: Translate;
  zh: boolean;
  onStartTutoring: (knowledgePointName: string) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [report, setReport] = useState<ObjectiveReport | null>(null);
  const loaded = openId !== null && report?.id === openId;

  useEffect(() => {
    if (!openId) return;
    const controller = new AbortController();
    fetchObjectiveReport(pathId, openId, { signal: controller.signal })
      .then(setReport)
      .catch(() => {
        if (!controller.signal.aborted) setReport(null);
      });
    return () => controller.abort();
  }, [pathId, openId, revision]);

  const toggle = useCallback((id: string) => {
    setOpenId((current) => (current === id ? null : id));
    setReport(null);
  }, []);

  return (
    <div className="flex gap-4 overflow-x-auto pb-2">
      {modules.map((module) => (
        <div
          key={module.id}
          className="flex w-64 shrink-0 flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--accent)]/30 p-3"
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-[var(--foreground)]">
              {module.name}
            </h3>
            <span className="text-xs text-[var(--muted-foreground)]">
              {module.mastered}/{module.total}
            </span>
          </div>

          {module.cards.map((card) => {
            const open = openId === card.id;
            const typeLabel = TYPE_LABEL[card.type] ?? {
              cn: card.type,
              en: card.type,
            };
            return (
              <div key={card.id}>
                <button
                  onClick={() => toggle(card.id)}
                  aria-expanded={open}
                  className={`w-full cursor-pointer rounded-md border bg-[var(--background)] p-3 text-left transition-colors hover:bg-[var(--accent)] ${STATUS_BORDER[card.status]}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm leading-snug text-[var(--foreground)]">
                      {card.name}
                    </span>
                    {STATUS_ICON[card.status]}
                  </div>
                  <div className="mt-2 flex items-center justify-between text-xs">
                    <span className="rounded bg-[var(--accent)] px-1.5 py-0.5 text-[var(--muted-foreground)]">
                      {tr(typeLabel.cn, typeLabel.en)}
                    </span>
                    <span
                      className={
                        card.status === "mastered"
                          ? "text-green-500"
                          : card.status === "learning"
                            ? "text-yellow-500"
                            : "text-[var(--muted-foreground)]"
                      }
                    >
                      {Math.round(card.mastery_level * 100)}%
                    </span>
                  </div>
                  {card.next_review_at && (
                    <div className="mt-1.5 flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
                      <BookOpen className="h-3 w-3" />
                      {tr("复习 ", "Review ")}
                      {formatRelative(card.next_review_at, zh)}
                    </div>
                  )}
                </button>

                {open && (
                  <div className="mt-2 rounded-md border border-[var(--border)] bg-[var(--background)] p-3">
                    {loaded && report ? (
                      <>
                        <ObjectiveDetail report={report} tr={tr} zh={zh} />
                        <button
                          onClick={() => onStartTutoring(card.name)}
                          className="mt-2 flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-2 text-xs text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
                        >
                          <MessageSquare className="h-3.5 w-3.5" />
                          {tr("开始辅导", "Start tutoring")}
                        </button>
                      </>
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

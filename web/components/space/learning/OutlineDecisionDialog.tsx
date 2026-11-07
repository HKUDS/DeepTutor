"use client";

import { X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  AskUserOptions,
  type AskUserCardData,
} from "@/components/chat/home/AskUserOptions";
import Tooltip from "@/shared/ui/Tooltip";
import { STUDY_COMPOSER_WIDTH } from "./MasteryComposer";

/**
 * A choice parked above the composer.
 *
 * The transcript keeps the tutor's explanation. The plans themselves stay
 * out of it until the learner asks to see them: the dock first says how
 * many there are, and the options appear only after that confirmation.
 * Submitting writes the pick into the conversation.
 */
export function ComposerChoiceDock({
  summary,
  confirmLabel,
  testId,
  children,
}: {
  summary: string;
  confirmLabel: string;
  testId: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation();
  return (
    <div
      data-testid={testId}
      className={`mx-auto w-full px-6 pb-2 ${STUDY_COMPOSER_WIDTH}`}
    >
      <div className="w-full overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-[0_8px_28px_rgba(0,0,0,0.08)]">
        {open ? (
          <>
            {/* Expanded is a page, not a one-way door: the learner can put it
                away and the summary row is still there to bring it back. */}
            <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-3.5 py-1.5">
              <p className="min-w-0 truncate text-[12px] leading-5 text-[var(--muted-foreground)]">
                {summary}
              </p>
              <Tooltip label={t("Close")} side="bottom">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label={t("Close")}
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </Tooltip>
            </div>
            <div className="max-h-[min(38vh,360px)] overflow-y-auto overscroll-contain">
              {children}
            </div>
          </>
        ) : (
          <div className="flex items-center justify-between gap-3 px-3.5 py-2.5">
            <p className="min-w-0 text-[13px] leading-5 text-[var(--foreground)]">
              {summary}
            </p>
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="shrink-0 rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
            >
              {confirmLabel}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function OutlineDecisionDialog({
  data,
  onSubmit,
}: {
  data: AskUserCardData;
  onSubmit: (payload: {
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }) => void | boolean | Promise<void | boolean>;
}) {
  const { t } = useTranslation();
  const count = data.payload.questions.reduce(
    (total, question) => total + Math.max(question.options.length, 1),
    0,
  );

  return (
    <ComposerChoiceDock
      testId="outline-decision-dialog"
      summary={t("{{count}} options need your choice", { count })}
      confirmLabel={t("Review the options")}
    >
      <AskUserOptions data={data} onSubmit={onSubmit} presentation="dialog" />
    </ComposerChoiceDock>
  );
}

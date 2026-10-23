"use client";

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  AskUserOptions,
  type AskUserCardData,
} from "@/components/chat/home/AskUserOptions";

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
  return (
    <div data-testid={testId} className="px-4 pb-2 sm:px-7">
      <div className="mx-auto w-full max-w-[900px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-[0_8px_28px_rgba(0,0,0,0.08)]">
        {open ? (
          <div className="max-h-[min(420px,46vh)] overflow-y-auto">{children}</div>
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

"use client";

import { Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { QuizVerdict, QuizVerdictReason } from "@/lib/quiz-verdict";

const RESULT_LABELS = {
  correct: "Correct",
  partial: "Partially correct",
  incorrect: "Incorrect",
  ungraded: "Not graded",
} as const;

const RESULT_STYLES = {
  correct:
    "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400",
  partial:
    "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400",
  incorrect: "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400",
  ungraded: "bg-[var(--muted)] text-[var(--muted-foreground)]",
} as const;

const REASON_LABELS: Record<QuizVerdictReason, string> = {
  vision_unavailable:
    "This model cannot read images, so the photo answer was not graded.",
  missing_verdict:
    "The judge returned no structured verdict, so this answer was not graded.",
  invalid_verdict:
    "The judge returned no structured verdict, so this answer was not graded.",
  low_confidence: "The judge was not confident enough to grade this answer.",
};

export default function QuizVerdictSummary({
  verdict,
}: {
  verdict: QuizVerdict;
}) {
  const { t } = useTranslation();
  const hasPoints =
    verdict.awarded_points !== undefined && verdict.max_points !== undefined;
  return (
    <div className="mb-2 space-y-1.5" data-testid="quiz-verdict">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${RESULT_STYLES[verdict.result]}`}
        >
          {t(RESULT_LABELS[verdict.result])}
        </span>
        {hasPoints && (
          <span className="text-[11px] font-medium text-[var(--muted-foreground)]">
            {t("{{awarded}} / {{max}} points", {
              awarded: verdict.awarded_points,
              max: verdict.max_points,
            })}
          </span>
        )}
      </div>
      {verdict.reason && (
        <div className="text-[11px] text-[var(--muted-foreground)]">
          {t(REASON_LABELS[verdict.reason])}
        </div>
      )}
      {verdict.steps.length > 0 && (
        <ol
          aria-label={t("Solution steps")}
          className="space-y-1 text-[12px] leading-snug"
        >
          {verdict.steps.map((step, index) => (
            <li key={`${index}-${step.label}`} className="flex gap-1.5">
              {step.ok ? (
                <Check
                  size={13}
                  aria-label={t("Correct")}
                  className="mt-0.5 shrink-0 text-green-600 dark:text-green-400"
                />
              ) : (
                <X
                  size={13}
                  aria-label={t("Incorrect")}
                  className="mt-0.5 shrink-0 text-red-600 dark:text-red-400"
                />
              )}
              <span>
                <span className="font-medium text-[var(--foreground)]">
                  {step.label}
                </span>
                {step.comment && (
                  <span className="text-[var(--muted-foreground)]">
                    {" — "}
                    {step.comment}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

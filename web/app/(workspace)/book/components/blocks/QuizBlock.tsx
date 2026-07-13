"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Eye, EyeOff, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { Block } from "@/lib/book-types";
import {
  isChoiceQuizQuestion,
  normalizeQuizQuestionType,
  resolveChoiceAnswerKey,
} from "@/lib/quiz-question-type";

export interface QuizAttemptArgs {
  questionId?: string;
  userAnswer?: string;
  isCorrect: boolean;
}

interface QuizQuestion {
  question_id?: string;
  question?: string;
  question_type?: string;
  options?: Record<string, string> | null;
  correct_answer?: string;
  explanation?: string;
  difficulty?: string;
}

export interface QuizBlockProps {
  block: Block;
  onAttempt?: (block: Block, args: QuizAttemptArgs) => void;
}

export default function QuizBlock({ block, onAttempt }: QuizBlockProps) {
  const { t } = useTranslation();
  const questions =
    (block.payload?.questions as QuizQuestion[] | undefined) || [];
  if (questions.length === 0) {
    return (
      <div className="text-sm text-[var(--muted-foreground)]">
        {t("No quiz questions generated.")}
      </div>
    );
  }
  return (
    <section>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--primary)]">
        <span className="h-px flex-1 bg-[var(--primary)]/20" />
        {t("Quick Check")}
        <span className="h-px flex-1 bg-[var(--primary)]/20" />
      </div>
      <div className="space-y-3">
        {questions.map((q, idx) => (
          <QuizQuestionCard
            key={q.question_id || idx}
            index={idx}
            question={q}
            onAttempt={(args) => onAttempt?.(block, args)}
          />
        ))}
      </div>
    </section>
  );
}

function QuizQuestionCard({
  index,
  question,
  onAttempt,
}: {
  index: number;
  question: QuizQuestion;
  onAttempt?: (args: QuizAttemptArgs) => void;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const reportedRef = useRef<string | null>(null);
  const normalizedType = normalizeQuizQuestionType(question.question_type);
  const options = question.options || {};
  const isChoice = isChoiceQuizQuestion(normalizedType);
  const correct = String(question.correct_answer || "").trim();
  const correctChoiceKey = resolveChoiceAnswerKey(correct, options);
  const reportKey = `${question.question_id || index}:${selected || ""}`;

  useEffect(() => {
    if (
      revealed &&
      selected &&
      reportedRef.current !== reportKey &&
      onAttempt
    ) {
      reportedRef.current = reportKey;
      onAttempt({
        questionId: question.question_id,
        userAnswer: selected,
        isCorrect: selected.toUpperCase() === correctChoiceKey,
      });
    }
  }, [
    reportKey,
    revealed,
    selected,
    onAttempt,
    question.question_id,
    correctChoiceKey,
  ]);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <span className="pt-0.5 text-sm font-medium text-[var(--foreground)]">
            {index + 1}.
          </span>
          <div className="min-w-0 flex-1">
            <MarkdownRenderer
              content={String(question.question || t("(missing)"))}
              variant="compact"
              className="font-sans text-sm font-medium text-[var(--foreground)] [&_ol]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_p]:my-1.5 [&_pre]:my-2 [&_ul]:my-2"
            />
          </div>
        </div>
        {question.difficulty && (
          <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
            {question.difficulty}
          </span>
        )}
      </div>

      {isChoice && Object.keys(options).length > 0 ? (
        <div className="mt-3 space-y-1.5">
          {Object.entries(options).map(([key, label]) => {
            const upperKey = key.toUpperCase();
            const isSelected = selected === upperKey;
            const isCorrect = revealed && upperKey === correctChoiceKey;
            const isWrongPick =
              revealed && isSelected && upperKey !== correctChoiceKey;
            return (
              <button
                key={key}
                onClick={() => setSelected(upperKey)}
                className={`flex w-full items-start gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                  isCorrect
                    ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
                    : isWrongPick
                      ? "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100"
                      : isSelected
                        ? "border-[var(--primary)] bg-[var(--primary)]/8 text-[var(--foreground)]"
                        : "border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] hover:border-[var(--primary)]/40"
                }`}
              >
                <span className="font-mono text-xs uppercase text-[var(--muted-foreground)]">
                  {upperKey}.
                </span>
                <span className="flex-1 whitespace-pre-wrap break-words">
                  {label}
                </span>
                {isCorrect && <CheckCircle2 className="mt-0.5 h-4 w-4" />}
                {isWrongPick && <XCircle className="mt-0.5 h-4 w-4" />}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="mt-2 text-xs text-[var(--muted-foreground)]">
          {normalizedType === "written"
            ? t("Think about your answer, then reveal the solution.")
            : t("Open response — click reveal to see the model answer.")}
        </div>
      )}

      <div className="mt-3 flex items-center justify-between gap-2">
        <button
          onClick={() => setRevealed((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-xs font-medium text-[var(--muted-foreground)] hover:border-[var(--primary)]/40 hover:text-[var(--primary)]"
        >
          {revealed ? (
            <EyeOff className="h-3.5 w-3.5" />
          ) : (
            <Eye className="h-3.5 w-3.5" />
          )}
          {revealed ? t("Hide answer") : t("Reveal answer")}
        </button>
        {revealed && correct && isChoice && (
          <span className="text-xs text-[var(--muted-foreground)]">
            {t("Answer")}:{" "}
            <span className="font-mono text-[var(--foreground)]">
              {correctChoiceKey || correct}
            </span>
          </span>
        )}
      </div>

      {revealed && correct && !isChoice && (
        <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--card)]/70 p-2">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
            {t("Answer")}
          </div>
          <MarkdownRenderer
            content={correct}
            variant="compact"
            className="font-sans text-sm text-[var(--foreground)] [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_p]:my-1.5 [&_pre]:my-2"
          />
        </div>
      )}

      {revealed && question.explanation && (
        <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 p-2">
          <MarkdownRenderer
            content={String(question.explanation)}
            variant="compact"
          />
        </div>
      )}
    </div>
  );
}

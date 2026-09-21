"use client";

import { useState } from "react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  Bookmark,
  CheckCheck,
  ExternalLink,
  MessageSquare,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import type { NotebookCategory, NotebookEntry } from "@/lib/notebook-api";
import { optionIsAnswer } from "@/lib/question-bank-answers";
import { bookRoute, masterySessionRoute } from "@/lib/learning-routes";
import CategoryMenu from "./CategoryMenu";
import { practiceMarkdown } from "@/lib/practice-content";

const SOURCE_LABELS: Record<NotebookEntry["source"], string> = {
  deep_question: "Deep Question",
  mastery_path: "Mastery Path",
  immersive_reading: "Immersive Reading",
  book: "Book",
  partner_chat: "Partner Chat",
  import: "Imported",
};

const ASSESSMENT_TYPE_LABELS: Record<string, string> = {
  quiz: "Quiz",
  focus_check: "Focus Check",
  qualitative: "Qualitative",
  review: "Review",
};

const QUESTION_TYPE_LABELS: Record<string, string> = {
  choice: "Single Choice",
  short: "Short Answer",
  open: "Short Answer",
  written: "Written Answer",
  concept: "Concept Check",
  fill_in_blank: "Fill in the Blank",
  single_choice: "Single Choice",
  multiple_choice: "Single Choice",
  mcq: "Single Choice",
  multi_choice: "Multiple Select",
  true_false: "True or False",
  fill_blank: "Fill in the Blank",
  short_answer: "Short Answer",
  free_response: "Short Answer",
  essay: "Short Answer",
  coding: "Coding",
};

const TREND_LABELS: Record<NotebookEntry["score_trend"], string> = {
  new: "First Attempt",
  improved: "Improved",
  declined: "Declined",
  unchanged: "Unchanged",
};

function entryResult(entry: NotebookEntry): string {
  if (entry.result) return entry.result;
  return entry.is_correct ? "correct" : "incorrect";
}

function resultBadge(entry: NotebookEntry): {
  label: string;
  className: string;
} {
  const result = entryResult(entry);
  if (result === "partial") {
    return {
      label: "Partially Correct",
      className: "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400",
    };
  }
  if (result === "ungraded") {
    return {
      label: "Not Graded",
      className: "bg-[var(--muted)] text-[var(--muted-foreground)]",
    };
  }
  if (result === "correct" || entry.is_correct) {
    return {
      label: "Correct",
      className: "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400",
    };
  }
  return {
    label: "Incorrect",
    className: "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400",
  };
}

interface QuestionCardProps {
  entry: NotebookEntry;
  mistakesOnly?: boolean;
  collapseAnswers?: boolean;
  categories: NotebookCategory[];
  selected: boolean;
  disabled: boolean;
  onToggleSelected: () => void;
  onToggleBookmark: () => void;
  onToggleResolved: () => void;
  onDelete: () => void;
  onFile: (categoryId: number) => Promise<boolean>;
  onUnfile: (categoryId: number) => Promise<boolean>;
  onCreateAndFile: (name: string) => Promise<boolean>;
}

function AnswerBlock({
  label,
  body,
  tone,
  isCode,
}: {
  label: string;
  body: string;
  tone: "correct" | "wrong" | "neutral";
  isCode: boolean;
}) {
  const toneClass =
    tone === "wrong"
      ? "border-red-200/60 bg-red-50/40 dark:border-red-900/40 dark:bg-red-950/15"
      : tone === "correct"
        ? "border-green-200/60 bg-green-50/40 dark:border-green-900/40 dark:bg-green-950/15"
        : "border-[var(--border)] bg-[var(--muted)]/30";
  const labelClass =
    tone === "wrong"
      ? "text-red-500 dark:text-red-400"
      : tone === "correct"
        ? "text-green-600 dark:text-green-400"
        : "text-[var(--muted-foreground)]";

  return (
    <div className={`rounded-lg border px-3 py-2 ${toneClass}`}>
      <div className={`mb-1 text-[10.5px] font-medium uppercase tracking-wide ${labelClass}`}>
        {label}
      </div>
      <div className="text-[13px] text-[var(--foreground)]">
        {body ? (
          <MarkdownRenderer
            content={
              isCode && !body.trimStart().startsWith("```") ? `\`\`\`python\n${body}\n\`\`\`` : body
            }
            variant="prose"
            className="text-[13px] leading-relaxed"
            enableMath
          />
        ) : (
          <span className="text-[var(--muted-foreground)]">—</span>
        )}
      </div>
    </div>
  );
}

/**
 * One bank entry.
 *
 * Reading comes first — question, what was answered, what was right — and
 * the organising controls sit in the header where they are reachable
 * without scrolling past the explanation.
 */
export default function QuestionCard({
  entry,
  mistakesOnly = false,
  collapseAnswers = false,
  categories,
  selected,
  disabled,
  onToggleSelected,
  onToggleBookmark,
  onToggleResolved,
  onDelete,
  onFile,
  onUnfile,
  onCreateAndFile,
}: QuestionCardProps) {
  const { t } = useTranslation();
  const [answersVisible, setAnswersVisible] = useState(!collapseAnswers);
  const options = entry.options || {};
  const hasOptions = Object.keys(options).length > 0;
  const isCode = entry.question_type === "coding";
  const filed = entry.categories || [];
  const result = entryResult(entry);
  const badge = resultBadge(entry);
  const showReviewState =
    !!entry.practice?.is_mistake || mistakesOnly || result === "incorrect" || result === "partial";

  return (
    <li
      className={`group rounded-xl border bg-[var(--card)] px-4 py-3.5 transition-all ${
        selected
          ? "border-[var(--primary)]/50 shadow-sm ring-1 ring-[var(--primary)]/20"
          : "border-[var(--border)] hover:border-[var(--border)] hover:shadow-sm"
      } ${disabled ? "pointer-events-none opacity-50" : ""}`}
    >
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelected}
          aria-label={t("Select")}
          className={`mt-1 h-3.5 w-3.5 shrink-0 cursor-pointer accent-[var(--primary)] transition-opacity ${
            selected ? "opacity-100" : "opacity-70 hover:opacity-100"
          }`}
        />

        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <span
              className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${badge.className}`}
            >
              {t(badge.label)}
            </span>
            {entry.difficulty && (
              <span
                className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase ${
                  entry.difficulty === "hard"
                    ? "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400"
                    : entry.difficulty === "medium"
                      ? "bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400"
                      : "bg-green-50 text-green-600 dark:bg-green-950/30 dark:text-green-400"
                }`}
              >
                {entry.difficulty}
              </span>
            )}
            {entry.question_type && (
              <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                {t(QUESTION_TYPE_LABELS[entry.question_type] || entry.question_type)}
              </span>
            )}
            <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
              {t(SOURCE_LABELS[entry.source] || "Unknown Source")}
            </span>
            {entry.assessment_type && ASSESSMENT_TYPE_LABELS[entry.assessment_type] ? (
              <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                {t(ASSESSMENT_TYPE_LABELS[entry.assessment_type])}
              </span>
            ) : null}
            {entry.score_trend && (
              <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                {t(TREND_LABELS[entry.score_trend] || "First Attempt")}
              </span>
            )}
            {showReviewState && (
              <span
                className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${
                  entry.resolved
                    ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                    : "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400"
                }`}
              >
                {entry.resolved ? t("Resolved") : t("Needs Review")}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <CategoryMenu
            categories={categories}
            activeIds={filed.map(category => category.id)}
            disabled={disabled}
            onPick={onFile}
            onUnpick={onUnfile}
            onCreate={onCreateAndFile}
          />
          <button
            type="button"
            onClick={onToggleBookmark}
            disabled={disabled}
            title={entry.bookmarked ? t("Remove Bookmark") : t("Bookmark")}
            className={`rounded-lg p-1.5 transition-colors disabled:opacity-40 ${
              entry.bookmarked
                ? "text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
            }`}
          >
            <Bookmark className="h-3.5 w-3.5" fill={entry.bookmarked ? "currentColor" : "none"} />
          </button>
          {showReviewState && (
            <button
              type="button"
              onClick={onToggleResolved}
              disabled={disabled}
              title={entry.resolved ? t("Reopen Review") : t("Mark Resolved")}
              className={`rounded-lg p-1.5 transition-colors disabled:opacity-40 ${
                entry.resolved
                  ? "text-green-600 dark:text-green-400"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
              }`}
            >
              {entry.resolved ? (
                <RotateCcw className="h-3.5 w-3.5" />
              ) : (
                <CheckCheck className="h-3.5 w-3.5" />
              )}
            </button>
          )}
          <button
            type="button"
            onClick={onDelete}
            disabled={disabled}
            title={t("Delete")}
            className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-40 dark:hover:bg-red-950/30"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div
        className="mt-3 min-w-0 text-[14px] text-foreground sm:pl-[1.625rem]"
        data-testid="question-stem"
      >
        <MarkdownRenderer
          content={practiceMarkdown(entry.question)}
          variant="prose"
          className="text-[14px] leading-relaxed [overflow-wrap:anywhere] [&_pre]:max-w-full [&_pre]:overflow-x-auto"
          allowHtml={false}
        />
      </div>

      {/* Aligned with the question text: checkbox (0.875rem) + gap (0.75rem). */}
      <div className="mt-3 space-y-2" style={{ paddingLeft: "1.625rem" }}>
        {hasOptions && (
          <div className="space-y-1">
            {Object.entries(options).map(([key, text]) => {
              const isUserAnswer =
                answersVisible && optionIsAnswer(key, text, entry.user_answer || "");
              const isCorrectAnswer =
                answersVisible && optionIsAnswer(key, text, entry.correct_answer || "");
              const isWrongPick = isUserAnswer && result === "incorrect";
              return (
                <div
                  key={key}
                  className={`flex items-start gap-2.5 rounded-lg border px-3 py-1.5 text-[13px] ${
                    isCorrectAnswer
                      ? "border-green-200 bg-green-50/60 dark:border-green-900 dark:bg-green-950/20"
                      : isWrongPick
                        ? "border-red-200 bg-red-50/60 dark:border-red-900 dark:bg-red-950/20"
                        : "border-transparent bg-[var(--muted)]/30"
                  }`}
                >
                  <span
                    className={`mt-px shrink-0 font-semibold ${
                      isCorrectAnswer
                        ? "text-green-600 dark:text-green-400"
                        : isWrongPick
                          ? "text-red-600 dark:text-red-400"
                          : "text-[var(--muted-foreground)]"
                    }`}
                  >
                    {key}.
                  </span>
                  <div
                    className={`min-w-0 flex-1 [overflow-wrap:anywhere] ${
                      isCorrectAnswer || isWrongPick
                        ? "text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)]"
                    }`}
                  >
                    <MarkdownRenderer
                      content={practiceMarkdown(text)}
                      variant="compact"
                      className="font-sans text-[13px] [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_p]:my-0"
                      allowHtml={false}
                    />
                  </div>
                  {isCorrectAnswer && (
                    <span className="mt-px shrink-0 text-[10px] font-medium text-green-600 dark:text-green-400">
                      ✓ {t("Correct")}
                    </span>
                  )}
                  {isWrongPick && (
                    <span className="mt-px shrink-0 text-[10px] font-medium text-red-600 dark:text-red-400">
                      ✗ {t("Your pick")}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
        <details
          open={collapseAnswers ? undefined : true}
          onToggle={event => setAnswersVisible(event.currentTarget.open)}
          className="space-y-2"
        >
          <summary className="cursor-pointer py-1 text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
            {t("Answer and explanation")}
          </summary>

          {!hasOptions && (
            <div className="grid gap-2 sm:grid-cols-2">
              <AnswerBlock
                label={`${t("Your Answer")}${
                  result === "correct" ? " ✓" : result === "incorrect" ? " ✗" : ""
                }`}
                body={entry.user_answer}
                tone={
                  result === "correct" ? "correct" : result === "incorrect" ? "wrong" : "neutral"
                }
                isCode={isCode}
              />
              <AnswerBlock
                label={t("Reference Answer")}
                body={entry.correct_answer}
                tone="correct"
                isCode={isCode}
              />
            </div>
          )}

          {entry.explanation && (
            <div className="rounded-lg border border-blue-200/60 bg-blue-50/30 px-3 py-2 dark:border-blue-900/40 dark:bg-blue-950/15">
              <div className="mb-1 text-[10.5px] font-medium uppercase tracking-wide text-blue-600 dark:text-blue-400">
                {t("Explanation")}
              </div>
              <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
                <MarkdownRenderer
                  content={entry.explanation}
                  variant="prose"
                  className="text-[13px] leading-relaxed"
                  enableMath
                />
              </div>
            </div>
          )}

          {!!entry.practice?.review_count && (
            <AnswerBlock
              label={t("Latest practice answer")}
              body={entry.practice.last_answer || ""}
              tone={entry.practice.last_rating === "again" ? "wrong" : "neutral"}
              isCode={isCode}
            />
          )}
        </details>
        <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5 text-[11px]">
          <div className="flex flex-wrap items-center gap-1.5">
            {filed.map(category => (
              <span
                key={category.id}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 py-0.5 pl-2 pr-1 text-[var(--muted-foreground)]"
              >
                {category.name}
                <button
                  type="button"
                  onClick={() => void onUnfile(category.id)}
                  disabled={disabled}
                  title={t("Remove tag")}
                  className="rounded p-0.5 transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}
            {entry.source !== "import" && !entry.session_id.startsWith("reading-notebook:") && (
              <Link
                href={
                  entry.source === "mastery_path" && (entry.mastery_path_id || entry.material_id)
                    ? masterySessionRoute(
                        entry.mastery_path_id || entry.material_id,
                        entry.session_id
                      )
                    : `/chat/${encodeURIComponent(entry.session_id)}`
                }
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <ExternalLink size={10} />
                {entry.session_title || t("Original Session")}
              </Link>
            )}
            {entry.source === "book" && entry.material_id && (
              <Link
                href={bookRoute(entry.material_id, entry.section_id)}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <ExternalLink size={10} />
                {entry.section_title || entry.material_title || t("Material")}
              </Link>
            )}
            {entry.source === "mastery_path" && entry.material_title && (
              <span className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[var(--muted-foreground)]">
                {entry.material_title}
                {entry.section_title ? ` · ${entry.section_title}` : ""}
              </span>
            )}
            {entry.source === "immersive_reading" &&
              (entry.material_title || entry.section_title || entry.material_id) && (
                <span className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[var(--muted-foreground)]">
                  {entry.section_title || entry.material_title || entry.material_id}
                </span>
              )}
            {entry.followup_session_id && (
              <Link
                href={`/chat/${encodeURIComponent(entry.followup_session_id)}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <MessageSquare size={10} />
                {t("Follow-up")}
              </Link>
            )}
          </div>
          {!!entry.practice?.is_mistake && !entry.resolved && (
            <span className="text-[var(--muted-foreground)]">
              {t("Next review: {{date}}", {
                date: new Date(entry.practice.due_at * 1000).toLocaleDateString(),
              })}
            </span>
          )}
          <span className="text-[var(--muted-foreground)]">
            {new Date(entry.created_at * 1000).toLocaleString()}
          </span>
        </div>
      </div>
    </li>
  );
}

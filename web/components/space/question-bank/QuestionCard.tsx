"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { Bookmark, ExternalLink, MessageSquare, Trash2, X } from "lucide-react";
import type { NotebookCategory, NotebookEntry } from "@/lib/notebook-api";
import CategoryMenu from "./CategoryMenu";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
);

interface QuestionCardProps {
  entry: NotebookEntry;
  categories: NotebookCategory[];
  selected: boolean;
  disabled: boolean;
  onToggleSelected: () => void;
  onToggleBookmark: () => void;
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
      <div
        className={`mb-1 text-[10.5px] font-medium uppercase tracking-wide ${labelClass}`}
      >
        {label}
      </div>
      <div className="text-[13px] text-[var(--foreground)]">
        {body ? (
          <MarkdownRenderer
            content={
              isCode && !body.trimStart().startsWith("```")
                ? `\`\`\`python\n${body}\n\`\`\``
                : body
            }
            variant="prose"
            className="text-[13px] leading-relaxed"
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
  categories,
  selected,
  disabled,
  onToggleSelected,
  onToggleBookmark,
  onDelete,
  onFile,
  onUnfile,
  onCreateAndFile,
}: QuestionCardProps) {
  const { t } = useTranslation();
  const options = entry.options || {};
  const hasOptions = Object.keys(options).length > 0;
  const isCode = entry.question_type === "coding";
  const filed = entry.categories || [];

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
            selected ? "opacity-100" : "opacity-0 group-hover:opacity-100"
          }`}
        />

        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <span
              className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${
                entry.is_correct
                  ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                  : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"
              }`}
            >
              {entry.is_correct ? t("Correct") : t("Incorrect")}
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
                {entry.question_type}
              </span>
            )}
          </div>

          <div className="text-[14px] font-medium text-[var(--foreground)]">
            <MarkdownRenderer
              content={entry.question}
              variant="prose"
              className="text-[14px] leading-relaxed"
            />
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <CategoryMenu
            categories={categories}
            activeIds={filed.map((category) => category.id)}
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
            <Bookmark
              className="h-3.5 w-3.5"
              fill={entry.bookmarked ? "currentColor" : "none"}
            />
          </button>
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

      {/* Aligned with the question text: checkbox (0.875rem) + gap (0.75rem). */}
      <div className="mt-3 space-y-2" style={{ paddingLeft: "1.625rem" }}>
        {hasOptions && (
          <div className="space-y-1">
            {Object.entries(options).map(([key, text]) => {
              const isUserAnswer =
                entry.user_answer?.toUpperCase() === key.toUpperCase();
              const isCorrectAnswer =
                entry.correct_answer?.toUpperCase() === key.toUpperCase();
              const isWrongPick = isUserAnswer && !entry.is_correct;
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
                  <span
                    className={`flex-1 ${
                      isCorrectAnswer || isWrongPick
                        ? "text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)]"
                    }`}
                  >
                    {text}
                  </span>
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

        {!hasOptions && (
          <div className="grid gap-2 sm:grid-cols-2">
            <AnswerBlock
              label={`${t("Your Answer")} ${entry.is_correct ? "✓" : "✗"}`}
              body={entry.user_answer}
              tone={entry.is_correct ? "correct" : "wrong"}
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
              />
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5 text-[11px]">
          <div className="flex flex-wrap items-center gap-1.5">
            {filed.map((category) => (
              <span
                key={category.id}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 py-0.5 pl-2 pr-1 text-[var(--muted-foreground)]"
              >
                {category.name}
                <button
                  type="button"
                  onClick={() => void onUnfile(category.id)}
                  disabled={disabled}
                  title={t("Remove from category")}
                  className="rounded p-0.5 transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}
            <Link
              href={`/?session=${encodeURIComponent(entry.session_id)}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <ExternalLink size={10} />
              {entry.session_title || t("Original Session")}
            </Link>
            {entry.followup_session_id && (
              <Link
                href={`/?session=${encodeURIComponent(entry.followup_session_id)}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <MessageSquare size={10} />
                {t("Follow-up")}
              </Link>
            )}
          </div>
          <span className="text-[var(--muted-foreground)]">
            {new Date(entry.created_at * 1000).toLocaleString()}
          </span>
        </div>
      </div>
    </li>
  );
}

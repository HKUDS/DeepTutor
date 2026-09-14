"use client";

import { useState } from "react";
import { Brain, Check, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Block } from "@/lib/book-types";

interface PracticeItem {
  question?: string;
  question_type?: string;
  options?: Record<string, string>;
  answer?: string;
  explanation?: string;
  difficulty?: string;
}

export interface RetrievalPracticeBlockProps {
  block: Block;
}

export default function RetrievalPracticeBlock({
  block,
}: RetrievalPracticeBlockProps) {
  const { t } = useTranslation();
  const items = (block.payload?.items as PracticeItem[] | undefined) || [];
  // One revealed item at a time keeps the recall attempt honest: seeing the
  // answer to question 3 shouldn't spoil question 4.
  const [revealed, setRevealed] = useState<number | null>(null);
  const [picked, setPicked] = useState<Record<number, string>>({});

  if (items.length === 0) return null;

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <Brain className="h-4 w-4 text-[var(--primary)]" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--primary)]">
          {t("Retrieval Practice")}
        </span>
        <span className="ml-auto text-xs text-[var(--muted-foreground)]">
          {items.length}
        </span>
      </div>
      <ol className="space-y-3">
        {items.map((item, index) => {
          const options = item.options || {};
          const isOpen = revealed === index;
          return (
            <li
              key={item.question || index}
              className="rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5"
            >
              <div className="text-sm font-medium leading-relaxed text-[var(--foreground)]">
                {index + 1}. {item.question}
              </div>
              {Object.keys(options).length > 0 && (
                <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                  {Object.entries(options).map(([label, body]) => {
                    const isPicked = picked[index] === label;
                    const isAnswer = isOpen && item.answer === label;
                    return (
                      <button
                        key={label}
                        onClick={() =>
                          setPicked((prev) => ({ ...prev, [index]: label }))
                        }
                        className={`flex items-start gap-1.5 rounded-lg border px-2 py-1.5 text-left text-xs transition ${
                          isAnswer
                            ? "border-emerald-400/60 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                            : isPicked
                              ? "border-[var(--primary)]/50 bg-[var(--primary)]/5"
                              : "border-[var(--border)] hover:border-[var(--primary)]/40"
                        }`}
                      >
                        <span className="font-semibold">{label}.</span>
                        <span className="flex-1">{body}</span>
                        {isAnswer && (
                          <Check className="mt-0.5 h-3 w-3 shrink-0" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
              {isOpen && (
                <div className="mt-2 space-y-1 rounded-lg bg-[var(--primary)]/5 px-2.5 py-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
                  {item.answer && (
                    <div>
                      <span className="font-semibold text-[var(--foreground)]">
                        {t("Correct Answer")}:
                      </span>{" "}
                      {item.answer}
                    </div>
                  )}
                  {item.explanation && (
                    <div>
                      <span className="font-semibold text-[var(--foreground)]">
                        {t("Explanation")}:
                      </span>{" "}
                      {item.explanation}
                    </div>
                  )}
                </div>
              )}
              <div className="mt-2 flex justify-end">
                <button
                  onClick={() => setRevealed(isOpen ? null : index)}
                  className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--muted-foreground)] transition hover:border-[var(--primary)]/40 hover:text-[var(--primary)]"
                >
                  {isOpen ? (
                    <>
                      <EyeOff className="h-3 w-3" />
                      {t("Hide answer")}
                    </>
                  ) : (
                    t("Show answer")
                  )}
                </button>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

"use client";

import { BookOpen, Lightbulb } from "lucide-react";
import { useState } from "react";
import type { Block } from "@/lib/book-types";

/**
 * YuEdu fork: 语法 block 渲染组件（英语/语文语法专用）。
 * 渲染句型模式 + 解释 + 例句（关键词高亮）+ 练习翻转卡。
 * Payload 形如:
 * {
 *   pattern: "Subject + have/has + past participle",
 *   explanation: "现在完成时表示过去发生的动作对现在造成的影响或结果。",
 *   examples: [
 *     { sentence: "I have finished my homework.", highlight: "have finished" },
 *     { sentence: "She has visited Paris twice.", highlight: "has visited" }
 *   ],
 *   exercise: { question: "选择正确的形式：He ___ (go) to school.", answer: "has gone", options: ["go", "goes", "has gone", "went"] }
 * }
 */
export default function GrammarBlock({ block }: { block: Block }) {
  const params = (block.payload as Record<string, unknown> | undefined) ?? {};
  const pattern = String(params.pattern ?? "");
  const explanation = String(params.explanation ?? "");
  const examples = Array.isArray(params.examples)
    ? params.examples.filter(
        (example): example is Record<string, unknown> =>
          typeof example === "object" &&
          example !== null &&
          !Array.isArray(example),
      )
    : [];
  const exercise =
    typeof params.exercise === "object" &&
    params.exercise !== null &&
    !Array.isArray(params.exercise)
      ? (params.exercise as Record<string, unknown>)
      : undefined;
  const question = String(exercise?.question ?? "");
  const answer = String(exercise?.answer ?? "");
  const options = Array.isArray(exercise?.options)
    ? exercise.options.filter(
        (option): option is string => typeof option === "string",
      )
    : [];
  const hasExercise = Boolean(question || answer || options.length > 0);
  const hasContent = Boolean(
    pattern || explanation || examples.length > 0 || hasExercise,
  );

  const [showAnswer, setShowAnswer] = useState(false);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
      {!hasContent && (
        <div className="flex h-24 items-center justify-center text-sm text-[var(--muted-foreground)]">
          暂无语法内容
        </div>
      )}

      {/* 句型模式 */}
      {pattern && (
        <div className="mb-3 flex items-start gap-2">
          <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-[var(--primary)]" />
          <div>
            <p className="text-xs font-medium text-[var(--muted-foreground)]">句型模式</p>
            <p className="mt-0.5 font-mono text-base font-medium text-[var(--foreground)]">
              {pattern}
            </p>
          </div>
        </div>
      )}

      {/* 解释 */}
      {explanation && (
        <div className="mb-3 flex items-start gap-2">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <p className="text-sm leading-relaxed text-[var(--foreground)]">{explanation}</p>
        </div>
      )}

      {/* 例句 */}
      {examples.length > 0 && (
        <div className="mb-3">
          <p className="mb-1.5 text-xs font-medium text-[var(--muted-foreground)]">例句</p>
          <ul className="space-y-1.5">
            {examples.map((ex, i) => {
              const sentence = String(ex.sentence ?? "");
              const highlight = String(ex.highlight ?? "");
              return (
                <li key={i} className="text-sm text-[var(--foreground)]">
                  {highlight && sentence.includes(highlight) ? (
                    <>
                      {sentence.split(highlight).map((part, j, arr) => (
                        <span key={j}>
                          {part}
                          {j < arr.length - 1 && (
                            <mark className="rounded bg-[var(--primary)]/15 px-0.5 font-medium text-[var(--primary)]">
                              {highlight}
                            </mark>
                          )}
                        </span>
                      ))}
                    </>
                  ) : (
                    sentence
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* 练习 */}
      {hasExercise && (
        <div className="border-t border-[var(--border)]/50 pt-3">
          <p className="mb-2 text-xs font-medium text-[var(--muted-foreground)]">练习</p>
          {question && (
            <p className="mb-2 text-sm text-[var(--foreground)]">{question}</p>
          )}
          {options.length > 0 && (
            <div className="grid grid-cols-2 gap-1.5">
              {options.map((opt, i) => {
                const isCorrect = opt === answer;
                const isSelected = opt === selectedOption;
                return (
                  <button
                    key={i}
                    onClick={() => {
                      setSelectedOption(opt);
                      setShowAnswer(true);
                    }}
                    className={`rounded-lg border px-3 py-1.5 text-left text-sm transition ${
                      showAnswer && isCorrect
                        ? "border-green-400 bg-green-50 text-green-700 dark:bg-green-500/10 dark:text-green-300"
                        : showAnswer && isSelected && !isCorrect
                          ? "border-rose-400 bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300"
                          : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:border-[var(--primary)]/50"
                    }`}
                  >
                    {opt}
                  </button>
                );
              })}
            </div>
          )}
          {showAnswer && answer && (
            <p className="mt-2 text-xs text-[var(--muted-foreground)]">
              ✓ 正确答案：<span className="font-medium text-[var(--foreground)]">{answer}</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

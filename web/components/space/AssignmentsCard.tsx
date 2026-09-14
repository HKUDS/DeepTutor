"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ClipboardList, X } from "lucide-react";

import {
  fetchMyAssignments,
  submitAssignment,
  type AssignmentItem,
  type StudentAssignment,
  type SubmitResponse,
} from "@/lib/assignments-api";

/**
 * The assignments card at the top of the Learning Space, next to the "today"
 * card: homework the class teacher assigned, an answering dialog for the ones
 * not done yet, and per-item right/wrong feedback on submit.
 *
 * Every state degrades quietly like TodayLearningCard: loading is a skeleton,
 * an error collapses to a one-line apology, and a learner with no assignments
 * renders nothing at all — homework is not owed every day.
 */

type Lang = { zh: string; en: string };

/** Option letters in bound order (A, B, C, …) — mirrors the bank's keys. */
function optionLetter(index: number): string {
  return String.fromCharCode(65 + index);
}

export default function AssignmentsCard() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : l.en), [zh]);

  const [assignments, setAssignments] = useState<StudentAssignment[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [active, setActive] = useState<StudentAssignment | null>(null);

  const reload = useCallback(() => {
    fetchMyAssignments()
      .then((data) => setAssignments(data.assignments))
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchMyAssignments()
      .then((data) => {
        if (!cancelled) setAssignments(data.assignments);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onSubmitted = useCallback(
    (_result: SubmitResponse) => {
      setActive(null);
      reload();
    },
    [reload],
  );

  if (failed) {
    return (
      <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
        <p className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {tr({ zh: "作业暂时无法加载，稍后再试。", en: "Couldn't load assignments — try again later." })}
        </p>
      </section>
    );
  }

  if (!assignments) {
    return (
      <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 shrink-0 animate-pulse rounded-lg bg-[var(--muted)]" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-3.5 w-32 animate-pulse rounded bg-[var(--muted)]" />
            <div className="h-3 w-56 max-w-full animate-pulse rounded bg-[var(--muted)]" />
          </div>
        </div>
      </section>
    );
  }

  if (assignments.length === 0) {
    // 没有作业就整张卡不出现：作业不是每天都有，空卡只会制造噪音。
    return null;
  }

  const todo = assignments.filter((assignment) => assignment.status === "todo");
  const done = assignments.filter((assignment) => assignment.status === "done");

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <header className="flex items-center gap-2">
        <ClipboardList size={16} strokeWidth={1.7} className="text-sky-600 dark:text-sky-400" />
        <h2 className="font-serif text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
          {tr({ zh: "我的作业", en: "My Assignments" })}
        </h2>
      </header>

      {todo.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {todo.map((assignment) => (
            <li key={assignment.assignment_id}>
              <button
                onClick={() => setActive(assignment)}
                className="group flex w-full items-center gap-3 rounded-lg border border-[var(--border)] p-2.5 text-left transition-colors hover:border-[var(--foreground)]/20"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium leading-tight text-[var(--foreground)]">
                    {assignment.title}
                  </span>
                  <span className="mt-0.5 block text-[11.5px] leading-snug text-[var(--muted-foreground)]">
                    {tr({
                      zh: `${assignment.items.length} 道题 · 待完成`,
                      en: `${assignment.items.length} questions · to do`,
                    })}
                    {assignment.due_at
                      ? ` · ${tr({ zh: "截止", en: "due" })} ${assignment.due_at.slice(0, 10)}`
                      : ""}
                  </span>
                </span>
                <span className="shrink-0 rounded-lg bg-sky-500/10 px-2.5 py-1 text-[12px] font-medium text-sky-600 dark:text-sky-400">
                  {tr({ zh: "去作答", en: "Answer" })}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {tr({ zh: "当前的作业都完成了。", en: "You're all caught up." })}
        </p>
      )}

      {done.length > 0 ? (
        <div className="mt-3 border-t border-[var(--border)] pt-3">
          <p className="text-[12px] leading-none text-[var(--muted-foreground)]">
            {tr({ zh: "已提交", en: "Submitted" })}
          </p>
          <ul className="mt-2 space-y-1.5">
            {done.map((assignment) => {
              const results = assignment.results ?? [];
              const correct = results.filter((result) => result.correct).length;
              return (
                <li
                  key={assignment.assignment_id}
                  className="flex items-center gap-3 rounded-lg border border-[var(--border)] p-2.5"
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium leading-tight text-[var(--foreground)]">
                    {assignment.title}
                  </span>
                  <span className="shrink-0 text-[12px] font-semibold tabular-nums text-[var(--foreground)]">
                    {correct}/{results.length}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {active ? (
        <AnswerDialog
          assignment={active}
          tr={tr}
          onClose={() => setActive(null)}
          onSubmitted={onSubmitted}
        />
      ) : null}
    </section>
  );
}

/** The answering dialog: one stem + radio options per question, then submit. */
function AnswerDialog({
  assignment,
  tr,
  onClose,
  onSubmitted,
}: {
  assignment: StudentAssignment;
  tr: (l: Lang) => string;
  onClose: () => void;
  onSubmitted: (result: SubmitResponse) => void;
}) {
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const answer = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await submitAssignment(
        assignment.assignment_id,
        assignment.items.map((item) => ({
          kp_id: item.kp_id,
          q_idx: item.q_idx,
          answer: answers[item.q_idx] ?? "",
        })),
      );
      onSubmitted(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : tr({ zh: "提交失败", en: "Submit failed" }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
      role="alertdialog"
      aria-modal="true"
      aria-label={assignment.title}
      onClick={() => {
        if (!busy) onClose();
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-[var(--foreground)]">
            {assignment.title}
          </h3>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] disabled:opacity-40"
            aria-label={tr({ zh: "关闭", en: "Close" })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4">
          {assignment.items.map((item, index) => (
            <QuestionBlock
              key={`${item.kp_id}-${item.q_idx}`}
              index={index + 1}
              item={item}
              selected={answers[item.q_idx]}
              onSelect={(letter) =>
                setAnswers((prev) => ({ ...prev, [item.q_idx]: letter }))
              }
              tr={tr}
            />
          ))}
        </div>

        {error && (
          <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
          >
            {tr({ zh: "取消", en: "Cancel" })}
          </button>
          <button
            type="button"
            onClick={answer}
            disabled={busy || Object.keys(answers).length === 0}
            className="rounded-lg bg-[var(--foreground)] px-4 py-1.5 text-sm font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {busy
              ? tr({ zh: "提交中…", en: "Submitting…" })
              : tr({ zh: "提交作业", en: "Submit" })}
          </button>
        </div>
      </div>
    </div>
  );
}

function QuestionBlock({
  index,
  item,
  selected,
  onSelect,
  tr,
}: {
  index: number;
  item: AssignmentItem;
  selected: string | undefined;
  onSelect: (value: string) => void;
  tr: (l: Lang) => string;
}) {
  const isShort = item.type === "short";
  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <p className="text-[13.5px] font-medium leading-relaxed text-[var(--foreground)]">
        <span className="mr-1.5 tabular-nums text-[var(--muted-foreground)]">
          {index}.
        </span>
        {item.stem}
      </p>
      {isShort ? (
        // 数学填空: 单行输入,判分交给后端的数学归一化 (1/2 ≡ 0.5)。
        <input
          type="text"
          value={selected ?? ""}
          maxLength={500}
          onChange={(e) => onSelect(e.target.value)}
          placeholder={tr({ zh: "输入答案…", en: "Type your answer…" })}
          aria-label={tr({ zh: "填空答案", en: "Fill-in answer" })}
          className="mt-2 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[13px] text-[var(--foreground)] outline-none transition-colors hover:border-teal-500/40 focus:border-teal-500/60"
        />
      ) : (
        <div className="mt-2 space-y-1.5">
          {item.options.map((body, optionIndex) => {
            const letter = optionLetter(optionIndex);
            const checked = selected === letter;
            return (
              <label
                key={letter}
                className={`flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-1.5 text-[13px] transition-colors ${
                  checked
                    ? "border-teal-500/60 bg-teal-500/10 text-[var(--foreground)]"
                    : "border-[var(--border)] text-[var(--foreground)] hover:border-teal-500/40"
                }`}
              >
                <input
                  type="radio"
                  name={`q-${item.kp_id}-${item.q_idx}`}
                  className="mt-0.5 accent-teal-600"
                  checked={checked}
                  onChange={() => onSelect(letter)}
                />
                <span className="min-w-0 flex-1 leading-relaxed">
                  <span className="mr-1 font-medium">{letter}.</span>
                  {body}
                </span>
              </label>
            );
          })}
        </div>
      )}
      <p className="sr-only">
        {isShort
          ? tr({ zh: "输入你的答案", en: "Type your answer" })
          : tr({ zh: "选择一个选项", en: "Pick one option" })}
      </p>
    </div>
  );
}

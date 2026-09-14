"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, FileText, KeyRound } from "lucide-react";
import type { ReorderedPaper, ReorderedQuestion } from "./types";

interface PaperPreviewProps {
  paper: ReorderedPaper;
}

function QuestionCard({
  question,
  number,
}: {
  question: ReorderedQuestion;
  number: string;
}) {
  return (
    <article className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="flex gap-3">
        <span className="flex h-7 min-w-7 items-center justify-center rounded-md bg-[var(--muted)] px-1 text-xs font-semibold text-[var(--foreground)]">
          {number}
        </span>
        <div className="min-w-0 flex-1">
          <p className="whitespace-pre-wrap text-sm leading-6 text-[var(--foreground)]">
            {question.question_text}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5 text-[10px] text-[var(--muted-foreground)]">
            <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">
              {question.question_type}
            </span>
            <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">
              {question.difficulty}
            </span>
            <span className="rounded bg-[var(--muted)] px-1.5 py-0.5 font-mono">
              {question.source_question_id}
            </span>
          </div>
          {question.images.length > 0 && (
            <div className="mt-3 space-y-1" aria-label="题目图片引用">
              {question.images.map((image) => (
                <div
                  key={image}
                  className="rounded-md border border-dashed border-[var(--border)] bg-[var(--muted)]/30 px-2.5 py-2 text-xs text-[var(--muted-foreground)]"
                >
                  图片：{image}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

export default function PaperPreview({ paper }: PaperPreviewProps) {
  const [view, setView] = useState<"student" | "answers">("student");
  const originalQuestions = useMemo(() => {
    const byId = new Map<string, ReorderedQuestion>();
    paper.sections.forEach((section) =>
      section.questions.forEach((question) => {
        if (!byId.has(question.source_question_id))
          byId.set(question.source_question_id, question);
      }),
    );
    return [...byId.values()].sort((a, b) => a.original_index - b.original_index);
  }, [paper]);

  const valid =
    paper.audit.input_count === paper.audit.output_count &&
    paper.audit.unassigned_ids.length === 0 &&
    paper.audit.duplicate_ids.length === 0 &&
    paper.missing_image_refs.length === 0;

  return (
    <section className="space-y-4" aria-label="题卷预览">
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--background)]/95 px-4 py-3 shadow-sm backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-semibold text-[var(--foreground)]">
          <span>
            输入 {paper.audit.input_count} → 输出 {paper.audit.output_count}
          </span>
          <span className="text-[var(--muted-foreground)]">/</span>
          <span>未分配 {paper.audit.unassigned_ids.length}</span>
          <span className="text-[var(--muted-foreground)]">/</span>
          <span>重复 {paper.audit.duplicate_ids.length}</span>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
            valid
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "bg-amber-500/10 text-amber-700 dark:text-amber-300"
          }`}
        >
          {valid ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
          {valid ? "可导出" : "需修正后导出"}
        </span>
      </div>

      {(paper.warnings.length > 0 || paper.missing_image_refs.length > 0) && (
        <div className="rounded-xl border border-amber-300/60 bg-amber-50/70 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
          {paper.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}

      {paper.answer_sheet && (
        <div className="flex w-fit rounded-lg bg-[var(--muted)] p-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={view === "student"}
            onClick={() => setView("student")}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              view === "student"
                ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                : "text-[var(--muted-foreground)]"
            }`}
          >
            <FileText size={14} /> 学生卷
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "answers"}
            onClick={() => setView("answers")}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              view === "answers"
                ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                : "text-[var(--muted-foreground)]"
            }`}
          >
            <KeyRound size={14} /> 教师答案页
          </button>
        </div>
      )}

      {view === "answers" && paper.answer_sheet ? (
        <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--muted)]/50 text-xs text-[var(--muted-foreground)]">
              <tr>
                <th className="px-4 py-3 font-medium">新题号</th>
                <th className="px-4 py-3 font-medium">原题号</th>
                <th className="px-4 py-3 font-medium">答案</th>
                <th className="px-4 py-3 font-medium">来源 ID</th>
              </tr>
            </thead>
            <tbody>
              {paper.answer_sheet.map((answer) => (
                <tr
                  key={answer.source_question_id}
                  className="border-t border-[var(--border)]"
                >
                  <td className="px-4 py-3 font-semibold">{answer.display_number}</td>
                  <td className="px-4 py-3">{answer.original_number}</td>
                  <td className="px-4 py-3">
                    {answer.answer || "原卷未提供答案"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--muted-foreground)]">
                    {answer.source_question_id}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--muted)]/20 p-4">
            <h3 className="mb-3 text-sm font-semibold text-[var(--foreground)]">原卷</h3>
            <div className="space-y-3">
              {originalQuestions.map((question) => (
                <QuestionCard
                  key={question.source_question_id}
                  question={question}
                  number={question.original_number}
                />
              ))}
            </div>
          </div>
          <div className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--muted)]/20 p-4">
            <h3 className="mb-3 text-sm font-semibold text-[var(--foreground)]">重排</h3>
            <div className="space-y-5">
              {paper.sections.map((section) => (
                <section key={section.id}>
                  <h4 className="mb-2 text-sm font-semibold text-[var(--foreground)]">
                    {section.title}
                  </h4>
                  <div className="space-y-3">
                    {section.questions.map((question) => (
                      <QuestionCard
                        key={`${section.id}-${question.source_question_id}`}
                        question={question}
                        number={question.display_number}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

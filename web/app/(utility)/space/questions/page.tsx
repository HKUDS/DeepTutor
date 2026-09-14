"use client";

import { useState } from "react";
import QuestionBankSection from "@/components/space/QuestionBankSection";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import ExamPaperAssembler from "./ExamPaperAssembler";
import PaperReorderEditor from "./PaperReorderEditor";
import type { QuestionsSpaceView } from "./types";

function tabClass(active: boolean): string {
  return `rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] ${
    active
      ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
  }`;
}

export default function SpaceQuestionsPage() {
  const { role } = useAuthStatus();
  // 组卷 is a teacher workflow — students keep the 题库 (错题本) + 题卷重排 tabs.
  const canAssemble = role === "admin" || role === "teacher";
  const [view, setView] = useState<QuestionsSpaceView>(() =>
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("tab") === "exam_assemble" &&
    (role === "admin" || role === "teacher")
      ? "exam_assemble"
      : "question_bank",
  );

  return (
    <div className="space-y-5">
      <div
        className="flex w-fit rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 p-1"
        role="tablist"
        aria-label="题目空间"
      >
        <button
          type="button"
          role="tab"
          aria-selected={view === "question_bank"}
          onClick={() => setView("question_bank")}
          className={tabClass(view === "question_bank")}
        >
          题库
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "paper_reorder"}
          onClick={() => setView("paper_reorder")}
          className={tabClass(view === "paper_reorder")}
        >
          题卷重排
        </button>
        {canAssemble && (
          <button
            type="button"
            role="tab"
            aria-selected={view === "exam_assemble"}
            onClick={() => setView("exam_assemble")}
            className={tabClass(view === "exam_assemble")}
          >
            组卷
          </button>
        )}
      </div>

      {view === "question_bank" ? (
        <QuestionBankSection />
      ) : view === "paper_reorder" ? (
        <PaperReorderEditor />
      ) : canAssemble ? (
        <ExamPaperAssembler />
      ) : (
        <QuestionBankSection />
      )}
    </div>
  );
}

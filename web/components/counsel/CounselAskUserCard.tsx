"use client";

import { Loader2, Send } from "lucide-react";
import { useState } from "react";
import type { AskUserPayload } from "@/components/chat/home/AskUserOptions";

type CounselAskUserCardProps = {
  payload: AskUserPayload;
  busy: boolean;
  onSubmit: (answers: Array<{ questionId: string; text: string }>) => void;
};

export default function CounselAskUserCard({
  payload,
  busy,
  onSubmit,
}: CounselAskUserCardProps) {
  const questions = payload.questions ?? [];
  const [answers, setAnswers] = useState<Record<string, string>>({});

  function handleSubmit() {
    const rows = questions.map((q) => ({
      questionId: q.id,
      text: (answers[q.id] ?? "").trim(),
    }));
    onSubmit(rows);
  }

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3">
      {payload.intro ? (
        <p className="mb-2 text-xs text-[var(--muted-foreground)]">{payload.intro}</p>
      ) : null}
      <div className="space-y-3">
        {questions.map((q) => (
          <div key={q.id}>
            <label
              htmlFor={`counsel-ask-${q.id}`}
              className="mb-1 block text-xs font-medium text-[var(--foreground)]"
            >
              {q.header || q.prompt}
            </label>
            {q.header && q.prompt !== q.header ? (
              <p className="mb-1.5 text-[11px] text-[var(--muted-foreground)]">{q.prompt}</p>
            ) : null}
            <textarea
              id={`counsel-ask-${q.id}`}
              rows={2}
              value={answers[q.id] ?? ""}
              onChange={(e) =>
                setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
              }
              disabled={busy}
              className="w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--ring)] disabled:opacity-60"
            />
          </div>
        ))}
      </div>
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          Submit answer
        </button>
      </div>
    </div>
  );
}

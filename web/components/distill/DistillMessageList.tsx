"use client";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";

export type DistillMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  stage?: string;
  source?: string;
};

function bubbleClass(msg: DistillMessage): string {
  if (msg.role === "user") {
    return "ml-auto bg-[var(--primary)] text-[var(--primary-foreground)]";
  }
  if (msg.stage === "writing") {
    return "mr-auto border border-emerald-500/40 bg-emerald-500/10 text-[var(--foreground)]";
  }
  if (msg.stage === "extracting") {
    return "mr-auto border border-sky-500/40 bg-sky-500/10 text-[var(--foreground)]";
  }
  if (msg.role === "system") {
    return "mx-auto border border-dashed border-[var(--border)] bg-[var(--background)]/60 text-[var(--muted-foreground)]";
  }
  return "mr-auto border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)]";
}

function useMarkdown(msg: DistillMessage): boolean {
  return msg.role !== "user" && msg.role !== "system";
}

export default function DistillMessageList({
  messages,
}: {
  messages: DistillMessage[];
}) {
  if (messages.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)]/50 p-4 text-xs leading-6 text-[var(--muted-foreground)]">
        <p className="mb-2 font-medium text-[var(--foreground)]">
          Distill — 2 steps
        </p>
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Paste a counseling methodology excerpt (not a live client transcript).</li>
          <li>
            Click{" "}
            <span className="font-medium text-[var(--foreground)]">Distill</span>{" "}
            to create or update DeepTutor skills.
          </li>
        </ol>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-6 ${bubbleClass(msg)} ${
              useMarkdown(msg) ? "" : "whitespace-pre-wrap"
            }`}
          >
            {msg.stage && (
              <div className="mb-1.5 text-[10px] uppercase tracking-wide opacity-70">
                {msg.stage}
              </div>
            )}
            {useMarkdown(msg) ? (
              <MarkdownRenderer
                content={msg.text}
                variant="compact"
                className="text-sm leading-6"
              />
            ) : (
              msg.text
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

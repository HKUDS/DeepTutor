"use client";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import {
  parseSimRecommendation,
  type SimRecommendation,
} from "@/lib/sim-recommend";

export type SimMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  stage?: string;
  source?: string;
  metadata?: Record<string, unknown>;
};

function bubbleClass(msg: SimMessage): string {
  if (msg.role === "user") {
    return "ml-auto bg-[var(--primary)] text-[var(--primary-foreground)]";
  }
  if (msg.stage === "supervisor") {
    return "mr-auto border border-amber-500/40 bg-amber-500/10 text-[var(--foreground)]";
  }
  if (msg.stage === "debrief") {
    return "mr-auto border border-violet-500/40 bg-violet-500/10 text-[var(--foreground)]";
  }
  if (msg.stage === "recommend") {
    return "mr-auto border border-emerald-500/40 bg-emerald-500/10 text-[var(--foreground)]";
  }
  if (msg.role === "system") {
    return "mx-auto border border-dashed border-[var(--border)] bg-[var(--background)]/60 text-[var(--muted-foreground)]";
  }
  return "mr-auto border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)]";
}

function useMarkdown(msg: SimMessage): boolean {
  if (msg.stage === "recommend") return false;
  return msg.role !== "user" && msg.role !== "system";
}

function RecommendCard({ rec, fallback }: { rec: SimRecommendation; fallback: string }) {
  return (
    <div>
      <div className="text-xs font-medium text-[var(--foreground)]">Next</div>
      <div className="mt-1 font-mono text-[11px] text-[var(--muted-foreground)]">
        {rec.kind} · {rec.targetId}
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
        {rec.reason || fallback}
      </p>
    </div>
  );
}

function MessageBody({ msg }: { msg: SimMessage }) {
  if (msg.stage === "recommend") {
    const rec = parseSimRecommendation(msg.metadata);
    if (rec) return <RecommendCard rec={rec} fallback={msg.text} />;
    return <>{msg.text}</>;
  }
  if (useMarkdown(msg)) {
    return (
      <MarkdownRenderer
        content={msg.text}
        variant="compact"
        className="text-sm leading-6"
      />
    );
  }
  return <>{msg.text}</>;
}

export default function SimMessageList({ messages }: { messages: SimMessage[] }) {
  if (messages.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)]/50 p-4 text-xs leading-6 text-[var(--muted-foreground)]">
        <p className="mb-2 font-medium text-[var(--foreground)]">
          Counsel sim — 3 steps
        </p>
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            Send a counselor line. The simulated visitor (and an opening, on
            a new session) will reply.
          </li>
          <li>
            Each turn also streams a short{" "}
            <span className="font-medium text-[var(--foreground)]">supervisor</span>{" "}
            note.
          </li>
          <li>
            Click <span className="font-medium text-[var(--foreground)]">结束</span>{" "}
            for a debrief.
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
            <MessageBody msg={msg} />
          </div>
        </div>
      ))}
    </div>
  );
}

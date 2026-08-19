"use client";

import { Lock } from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { IntakeMessage, IntakeSeat } from "@/lib/intake-transcript";

type IntakeMessageListProps = {
  messages: IntakeMessage[];
  seat: IntakeSeat;
};

function bubbleClass(msg: IntakeMessage): string {
  if (msg.role === "user") {
    return "ml-auto bg-[var(--primary)] text-[var(--primary-foreground)]";
  }
  if (msg.stage === "supervisor") {
    return "mr-auto border border-sky-500/40 bg-sky-500/10 text-[var(--foreground)]";
  }
  if (msg.stage === "debrief") {
    return "mr-auto border border-violet-500/40 bg-violet-500/10 text-[var(--foreground)]";
  }
  if (msg.role === "system") {
    return "mx-auto border border-dashed border-[var(--border)] bg-[var(--background)]/60 text-[var(--muted-foreground)]";
  }
  return "mr-auto border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)]";
}

function showSource(source?: string): boolean {
  if (!source) return false;
  return source !== "intake_visitor" && source !== "intake_trainee";
}

function useMarkdown(msg: IntakeMessage): boolean {
  return msg.role !== "user" && msg.role !== "system";
}

export default function IntakeMessageList({
  messages,
  seat,
}: IntakeMessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)]/50 p-4 text-xs leading-6 text-[var(--muted-foreground)]">
        <p className="mb-2 font-medium text-[var(--foreground)]">
          Live intake supervision — 3 seats
        </p>
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-[var(--foreground)]">Visitor:</span>{" "}
            send the first message → you get a{" "}
            <code className="rounded bg-[var(--muted)] px-1">room_id</code>.
          </li>
          <li>
            <span className="font-medium text-[var(--foreground)]">Trainee:</span>{" "}
            switch seats and send counselor lines. Supervisor notes appear with a lock.
          </li>
          <li>
            <span className="font-medium text-[var(--foreground)]">Supervisor:</span>{" "}
            read-only view of the full transcript including private coaching notes.
          </li>
          <li>
            <span className="font-medium text-[var(--foreground)]">结束:</span>{" "}
            on Trainee, end the session for a debrief.
          </li>
        </ol>
        <p className="mt-3 opacity-80">
          {seat === "visitor"
            ? "You are on Visitor — start with step 1."
            : seat === "trainee"
              ? "You are on Trainee — complete step 1 as Visitor first if there is no room yet."
              : "You are on Supervisor — read-only. Start the room from Visitor first."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {messages.map((msg) => {
        const isSupervisor = msg.stage === "supervisor";
        const metaStage =
          msg.stage && msg.stage !== "supervisor" ? msg.stage : null;
        const metaSource = showSource(msg.source) ? msg.source : null;
        const showMeta =
          isSupervisor || metaStage || metaSource || Boolean(msg.localSeat);

        return (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-6 ${bubbleClass(msg)} ${
                useMarkdown(msg) ? "" : "whitespace-pre-wrap"
              }`}
            >
              {showMeta && (
                <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[10px] uppercase tracking-wide opacity-70">
                  {isSupervisor && (
                    <span className="inline-flex items-center gap-1 font-semibold text-sky-600 dark:text-sky-400">
                      <Lock className="h-3 w-3" aria-hidden />
                      supervisor
                    </span>
                  )}
                  {metaStage && <span>{metaStage}</span>}
                  {metaSource && <span>· {metaSource}</span>}
                  {msg.localSeat && <span>· you ({msg.localSeat})</span>}
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
        );
      })}
    </div>
  );
}

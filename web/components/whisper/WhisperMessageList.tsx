"use client";

import { Lock } from "lucide-react";
import type { WhisperMessage, WhisperSeat } from "@/lib/whisper-transcript";

type WhisperMessageListProps = {
  messages: WhisperMessage[];
  seat: WhisperSeat;
};

function bubbleClass(msg: WhisperMessage): string {
  if (msg.role === "user") {
    return "ml-auto bg-[var(--primary)] text-[var(--primary-foreground)]";
  }
  if (msg.stage === "whisper") {
    return "mr-auto border border-amber-500/40 bg-amber-500/10 text-[var(--foreground)]";
  }
  if (msg.stage === "debrief") {
    return "mr-auto border border-violet-500/40 bg-violet-500/10 text-[var(--foreground)]";
  }
  if (msg.role === "system") {
    return "mx-auto border border-dashed border-[var(--border)] bg-[var(--background)]/60 text-[var(--muted-foreground)]";
  }
  return "mr-auto border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)]";
}

export default function WhisperMessageList({
  messages,
  seat,
}: WhisperMessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)]/50 p-4 text-xs leading-5 text-[var(--muted-foreground)]">
        {seat === "visitor"
          ? "Speak as the visitor. The first reply will include a room_id for the trainee seat."
          : "Send counselor lines here. Private whisper notes appear with a lock badge."}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {messages.map((msg) => {
        const isWhisper = msg.stage === "whisper";
        return (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-6 whitespace-pre-wrap ${bubbleClass(msg)}`}
            >
              {(isWhisper || msg.stage || msg.source) && (
                <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[10px] uppercase tracking-wide opacity-70">
                  {isWhisper && (
                    <span className="inline-flex items-center gap-1 font-semibold text-amber-600 dark:text-amber-400">
                      <Lock className="h-3 w-3" aria-hidden />
                      whisper
                    </span>
                  )}
                  {msg.stage && msg.stage !== "whisper" && (
                    <span>{msg.stage}</span>
                  )}
                  {msg.source && <span>· {msg.source}</span>}
                  {msg.localSeat && <span>· you ({msg.localSeat})</span>}
                </div>
              )}
              {msg.text}
            </div>
          </div>
        );
      })}
    </div>
  );
}

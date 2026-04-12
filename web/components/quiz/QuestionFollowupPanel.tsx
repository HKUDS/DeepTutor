"use client";

import {
  ChevronDown,
  Loader2,
  MessageSquarePlus,
  SendHorizonal,
  Sparkles,
} from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { QuizQuestion } from "@/lib/quiz-types";

export interface FollowupMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface FollowupThreadState {
  isOpen: boolean;
  input: string;
  isStreaming: boolean;
  currentStage: string;
  sessionId: string | null;
  activeTurnId: string | null;
  messages: FollowupMessage[];
  error: string | null;
}

interface QuestionFollowupPanelProps {
  question: QuizQuestion;
  questionNumber: number;
  thread: FollowupThreadState;
  onToggle: () => void;
  onInputChange: (value: string) => void;
  onSend: () => void;
}

function titleCase(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function QuestionFollowupPanel({
  question,
  questionNumber,
  thread,
  onToggle,
  onInputChange,
  onSend,
}: QuestionFollowupPanelProps) {
  const visibleMessages = thread.messages.filter((message) => message.role !== "system");

  return (
    <div className="border-t border-[var(--border)] bg-[var(--card)]/30 px-3 py-2">
      <div className="overflow-hidden rounded-lg border border-[var(--border)]/80 bg-[var(--background)]/88 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors hover:bg-[var(--muted)]/14"
        >
          <div className="min-w-0 flex items-center gap-2 text-[12px] font-medium text-[var(--foreground)]">
              <MessageSquarePlus size={13} className="text-[var(--primary)]" />
              <span>Follow-up Chat</span>
          </div>
          <div className="ml-auto flex min-w-0 items-center gap-1.5">
            <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-[var(--muted-foreground)]">
              Q{questionNumber}
            </span>
            {question.question_type && (
              <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-[var(--muted-foreground)]">
                {question.question_type}
              </span>
            )}
            {question.difficulty && (
              <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-[var(--muted-foreground)]">
                {question.difficulty}
              </span>
            )}
            {thread.isStreaming && (
              <Loader2 size={11} className="animate-spin text-[var(--primary)]" />
            )}
            <ChevronDown
              size={14}
              className={`shrink-0 text-[var(--muted-foreground)] transition-transform ${
                thread.isOpen ? "rotate-180" : ""
              }`}
            />
          </div>
        </button>

        {thread.isOpen && (
          <>
            <div className="max-h-[220px] space-y-2 overflow-y-auto border-t border-[var(--border)]/60 px-3 py-2.5">
              {visibleMessages.length === 0 ? (
                <div className="rounded-md border border-dashed border-[var(--border)]/80 bg-[var(--muted)]/14 px-3 py-2.5 text-[12px] leading-[1.55] text-[var(--muted-foreground)]">
                  <div className="mb-1 flex items-center gap-1.5 font-medium text-[var(--foreground)]">
                    <Sparkles size={11} className="text-[var(--primary)]" />
                    Ask anything about this question
                  </div>
                  <div>
                    Try: why this answer is correct, where your reasoning went wrong, or ask for a cleaner explanation.
                  </div>
                </div>
              ) : (
                visibleMessages.map((message, index) => (
                  <div
                    key={`${message.role}-${index}`}
                    className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
                  >
                    <div
                      className={`max-w-[88%] rounded-[16px] px-3 py-2 text-[13px] leading-[1.7] ${
                        message.role === "user"
                          ? "rounded-br-md bg-[var(--primary)] text-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
                          : "rounded-bl-md border border-[var(--border)]/80 bg-[var(--card)] text-[var(--foreground)]"
                      }`}
                    >
                      {message.role === "assistant" ? (
                        <MarkdownRenderer content={message.content} variant="compact" />
                      ) : (
                        <div className="whitespace-pre-wrap break-words">{message.content}</div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="border-t border-[var(--border)]/70 bg-[var(--card)]/45 px-3 py-2">
              {thread.currentStage && thread.isStreaming && (
                <div className="mb-1 text-[10px] text-[var(--muted-foreground)]">
                  {titleCase(thread.currentStage)}...
                </div>
              )}
              {thread.error && (
                <div className="mb-1 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[10px] text-red-700 dark:border-red-950/50 dark:bg-red-950/20 dark:text-red-300">
                  {thread.error}
                </div>
              )}
              <div className="flex items-end gap-1.5">
                <textarea
                  value={thread.input}
                  onChange={(event) => onInputChange(event.target.value)}
                  rows={2}
                  disabled={thread.isStreaming}
                  placeholder="Ask a follow-up question about this item..."
                  className="min-h-[56px] flex-1 resize-none rounded-md border border-[var(--border)]/80 bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)]/35"
                />
                <button
                  onClick={onSend}
                  disabled={!thread.input.trim() || thread.isStreaming}
                  className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 text-[12px] font-medium text-white transition-opacity disabled:opacity-35"
                >
                  {thread.isStreaming ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : (
                    <SendHorizonal size={11} />
                  )}
                  Send
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

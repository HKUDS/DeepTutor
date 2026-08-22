"use client";

import { Lock } from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
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

function showSource(source?: string): boolean {
  if (!source) return false;
  return source !== "whisper_visitor" && source !== "whisper_trainee";
}

// A plain predicate, not a React hook. Under a `use` prefix it read as one, and
// calling it inside the map below tripped react-hooks/rules-of-hooks.
function rendersMarkdown(msg: WhisperMessage): boolean {
  return msg.role !== "user" && msg.role !== "system";
}

export default function WhisperMessageList({
  messages,
  seat,
}: WhisperMessageListProps) {
  const { t } = useTranslation();

  if (messages.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)]/50 p-4 text-xs leading-6 text-[var(--muted-foreground)]">
        <p className="mb-2 font-medium text-[var(--foreground)]">
          {t("Dual-seat whisper — 3 steps")}
        </p>
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>
            <span className="font-medium text-[var(--foreground)]">
              {t("Visitor")}:
            </span>{" "}
            {t("send the first message to get a room id.")}
          </li>
          <li>
            <span className="font-medium text-[var(--foreground)]">
              {t("Trainee")}:
            </span>{" "}
            {t(
              "switch seats and send counselor lines. Private notes show with a lock.",
            )}
          </li>
          <li>
            <span className="font-medium text-[var(--foreground)]">
              {t("End session")}:
            </span>{" "}
            {t("on Trainee, end the room for a debrief.")}
          </li>
        </ol>
        <p className="mt-3 opacity-80">
          {seat === "visitor"
            ? t("You are on Visitor — start with step 1.")
            : t(
                "You are on Trainee — complete step 1 as Visitor first if there is no room yet.",
              )}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {messages.map((msg) => {
        const isWhisper = msg.stage === "whisper";
        const metaStage =
          msg.stage && msg.stage !== "whisper" ? msg.stage : null;
        const metaSource = showSource(msg.source) ? msg.source : null;
        const showMeta =
          isWhisper || metaStage || metaSource || Boolean(msg.localSeat);

        return (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-6 ${bubbleClass(msg)} ${
                rendersMarkdown(msg) ? "" : "whitespace-pre-wrap"
              }`}
            >
              {showMeta && (
                <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[10px] uppercase tracking-wide opacity-70">
                  {isWhisper && (
                    <span className="inline-flex items-center gap-1 font-semibold text-amber-600 dark:text-amber-400">
                      <Lock className="h-3 w-3" aria-hidden />
                      {t("whisper")}
                    </span>
                  )}
                  {metaStage && <span>{metaStage}</span>}
                  {metaSource && <span>· {metaSource}</span>}
                  {msg.localSeat && (
                    <span>
                      · {t("you")} ({msg.localSeat})
                    </span>
                  )}
                </div>
              )}
              {rendersMarkdown(msg) ? (
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

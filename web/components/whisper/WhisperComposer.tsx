"use client";

import type { KeyboardEvent } from "react";
import { Loader2, Send } from "lucide-react";
import { shouldSubmitOnEnter } from "@/lib/composer-keyboard";
import { useImeComposing } from "@/lib/use-ime-composing";
import type { WhisperSeat } from "@/lib/whisper-transcript";

type WhisperComposerProps = {
  seat: WhisperSeat;
  draft: string;
  busy: boolean;
  /** Blocks Send / Enter submit (busy, crisis, closed, trainee without room). */
  sendDisabled: boolean;
  /** Only lock the textarea for terminal room states — never for busy. */
  inputDisabled: boolean;
  showEndButton: boolean;
  endDisabled: boolean;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onEnd: () => void;
};

export default function WhisperComposer({
  seat,
  draft,
  busy,
  sendDisabled,
  inputDisabled,
  showEndButton,
  endDisabled,
  onDraftChange,
  onSend,
  onEnd,
}: WhisperComposerProps) {
  const { isComposingRef, onCompositionStart, onCompositionEnd } =
    useImeComposing();

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (!shouldSubmitOnEnter(event, isComposingRef.current)) return;
    event.preventDefault();
    if (!sendDisabled) onSend();
  }

  return (
    <div className="border-t border-[var(--border)] bg-[var(--card)]/40 px-4 py-3 backdrop-blur">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onCompositionStart={onCompositionStart}
            onCompositionEnd={onCompositionEnd}
            disabled={inputDisabled}
            rows={2}
            placeholder={
              seat === "visitor"
                ? "Message as visitor…"
                : "Counselor line as trainee…"
            }
            className="min-h-[2.75rem] flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-sm outline-none transition-colors focus:border-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-60"
            aria-label={seat === "visitor" ? "Visitor message" : "Trainee message"}
          />
          <button
            type="button"
            onClick={onSend}
            disabled={sendDisabled || !draft.trim()}
            className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-[var(--primary)] px-3.5 text-sm font-medium text-[var(--primary-foreground)] transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Send"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            Send
          </button>
        </div>
        {showEndButton && (
          <div className="flex justify-end">
            <button
              type="button"
              onClick={onEnd}
              disabled={endDisabled}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              结束
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

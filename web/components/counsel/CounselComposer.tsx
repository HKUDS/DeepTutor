"use client";

import type { KeyboardEvent } from "react";
import { Loader2, Send } from "lucide-react";
import { shouldSubmitOnEnter } from "@/lib/composer-keyboard";
import { useImeComposing } from "@/lib/use-ime-composing";

type CounselComposerProps = {
  draft: string;
  busy: boolean;
  sendDisabled: boolean;
  inputDisabled: boolean;
  onDraftChange: (value: string) => void;
  onSend: () => void;
};

export default function CounselComposer({
  draft,
  busy,
  sendDisabled,
  inputDisabled,
  onDraftChange,
  onSend,
}: CounselComposerProps) {
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
        <textarea
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={onCompositionStart}
          onCompositionEnd={onCompositionEnd}
          disabled={inputDisabled}
          rows={2}
          placeholder="Share as the visitor…"
          className="min-h-[2.75rem] flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-sm outline-none transition-colors focus:border-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-60"
          aria-label="Visitor message"
        />
        <div className="flex items-center justify-end gap-2">
          {busy && (
            <p className="mr-auto text-[11px] text-[var(--muted-foreground)]">Waiting…</p>
          )}
          <button
            type="button"
            onClick={onSend}
            disabled={sendDisabled || !draft.trim()}
            className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-[var(--primary)] px-3.5 text-sm font-medium text-[var(--primary-foreground)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

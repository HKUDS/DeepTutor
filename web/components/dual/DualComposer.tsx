"use client";

import { Loader2 } from "lucide-react";

type DualComposerProps = {
  busy: boolean;
  continueDisabled: boolean;
  endDisabled: boolean;
  onContinue: () => void;
  onEnd: () => void;
};

export default function DualComposer({
  busy,
  continueDisabled,
  endDisabled,
  onContinue,
  onEnd,
}: DualComposerProps) {
  return (
    <div className="border-t border-[var(--border)] bg-[var(--card)]/40 px-4 py-3 backdrop-blur">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onEnd}
            disabled={endDisabled}
            className="rounded-xl border border-[var(--border)] px-3.5 py-2 text-sm font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            结束
          </button>
          <button
            type="button"
            onClick={onContinue}
            disabled={continueDisabled}
            className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-[var(--primary)] px-3.5 text-sm font-medium text-[var(--primary-foreground)] transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            继续
          </button>
        </div>
        {busy && (
          <p className="text-right text-[11px] text-[var(--muted-foreground)]">
            Waiting…
          </p>
        )}
      </div>
    </div>
  );
}

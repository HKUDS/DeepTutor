"use client";

import { Loader2, PauseCircle, Play } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Book } from "@/lib/book-types";

export interface BookPausedBannerProps {
  book: Book | null;
  onResume: () => void;
  resuming?: boolean;
}

/**
 * Shown when compilation stopped itself after repeated provider failures.
 *
 * The reassurance is the point: the book stopped *early* precisely so the
 * remaining chapters weren't ground into half-generated debris, and picking up
 * where it left off costs only the work that is genuinely missing.
 */
export default function BookPausedBanner({
  book,
  onResume,
  resuming = false,
}: BookPausedBannerProps) {
  const { t } = useTranslation();
  if (!book || book.status !== "paused") return null;

  const reason = String(book.metadata?.pause_reason || "").trim();

  return (
    <div className="border-b border-amber-300/70 bg-amber-50 px-8 py-3 text-amber-950 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100">
      <div className="mx-auto flex w-full max-w-[78ch] items-start gap-3">
        <PauseCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold">
            {t("Generation paused")}
          </div>
          <p className="mt-0.5 text-xs leading-relaxed opacity-90">
            {t(
              "Your model provider kept refusing requests, so the remaining chapters were left untouched rather than half-written. Everything generated so far is saved.",
            )}
          </p>
          {reason && (
            <code className="mt-1.5 block truncate rounded bg-white/50 px-1.5 py-0.5 text-[11px] dark:bg-white/10">
              {reason}
            </code>
          )}
        </div>
        <button
          type="button"
          onClick={onResume}
          disabled={resuming}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-current px-2.5 py-1 text-xs font-medium hover:bg-white/40 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/10"
        >
          {resuming ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          {resuming ? t("Resuming…") : t("Resume generation")}
        </button>
      </div>
    </div>
  );
}

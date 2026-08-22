"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, RotateCw, TriangleAlert, X } from "lucide-react";

/**
 * Indeterminate loading overlay shown while a chat session is fetched from
 * the server (e.g. when opening an entry from chat history). It replaces the
 * misleading welcome screen during the load and lets the user cancel.
 *
 * The indicator is deliberately indeterminate: a session fetch reports no
 * real progress, so a spinner is honest where a percentage bar would be
 * fabricated. After a while we surface a reassurance hint.
 *
 * A load that fails or times out ends here too, as a terminal state with a
 * retry: a conversation whose fetch did not arrive is not the same thing as
 * one that is still arriving, and the difference has to be visible or the
 * spinner becomes a lie the user cannot act on.
 */
interface SessionLoadingViewProps {
  onCancel?: () => void;
  /** Render the terminal failure state instead of the spinner. */
  failed?: boolean;
  onRetry?: () => void;
}

// After this long with no response, reassure the user it is still working.
const STILL_LOADING_AFTER_MS = 8000;

export default function SessionLoadingView({
  onCancel,
  failed = false,
  onRetry,
}: SessionLoadingViewProps) {
  const { t } = useTranslation();
  const [showHint, setShowHint] = useState(false);

  useEffect(() => {
    if (failed) return;
    const timer = setTimeout(() => setShowHint(true), STILL_LOADING_AFTER_MS);
    return () => clearTimeout(timer);
  }, [failed]);

  return (
    <div className="animate-fade-in relative flex h-full flex-col items-center justify-center gap-4 px-6">
      {/* Cancel button — top-right */}
      {onCancel ? (
        <button
          type="button"
          aria-label={t("Cancel")}
          onClick={onCancel}
          className="absolute end-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <X className="h-4 w-4" />
        </button>
      ) : null}

      {/* Logo + spinner (or the failure mark) */}
      <div className="flex items-center gap-3">
        <img
          src="/logo_black.png"
          alt="DeepTutor"
          width={32}
          height={32}
          className="h-8 w-8 select-none"
          draggable={false}
        />
        {failed ? (
          <TriangleAlert className="h-5 w-5 text-[var(--destructive)]" />
        ) : (
          <Loader2 className="h-5 w-5 animate-spin text-[var(--primary)]" />
        )}
      </div>

      {/* Primary message */}
      <p className="text-sm font-medium text-[var(--foreground)]">
        {failed ? t("Failed to load session") : t("Loading conversation")}
      </p>

      {/* Terminal state: the one action that can still succeed */}
      {failed && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)]"
        >
          <RotateCw className="h-3.5 w-3.5" />
          {t("Retry")}
        </button>
      ) : null}

      {/* Slow-load hint */}
      {showHint ? (
        <p className="animate-fade-in text-[12px] text-[var(--muted-foreground)]">
          {t("Still loading…")}
        </p>
      ) : null}
    </div>
  );
}

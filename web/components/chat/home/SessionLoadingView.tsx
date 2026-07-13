"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, X } from "lucide-react";

/**
 * Indeterminate loading overlay shown while a chat session is fetched from
 * the server (e.g. when opening an entry from chat history). It replaces the
 * misleading welcome screen during the load and lets the user cancel.
 *
 * The indicator is deliberately indeterminate: a session fetch reports no
 * real progress, so a spinner is honest where a percentage bar would be
 * fabricated. After a while we surface a reassurance hint.
 */
interface SessionLoadingViewProps {
  onCancel?: () => void;
}

// After this long with no response, reassure the user it is still working.
const STILL_LOADING_AFTER_MS = 8000;

export default function SessionLoadingView({
  onCancel,
}: SessionLoadingViewProps) {
  const { t } = useTranslation();
  const [showHint, setShowHint] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShowHint(true), STILL_LOADING_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);

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

      {/* Logo + spinner */}
      <div className="flex items-center gap-3">
        <img
          src="/logo_black.png"
          alt="DeepTutor"
          width={32}
          height={32}
          className="h-8 w-8 select-none"
          draggable={false}
        />
        <Loader2 className="h-5 w-5 animate-spin text-[var(--primary)]" />
      </div>

      {/* Primary message */}
      <p className="text-sm font-medium text-[var(--foreground)]">
        {t("Loading conversation")}
      </p>

      {/* Slow-load hint */}
      {showHint ? (
        <p className="animate-fade-in text-[12px] text-[var(--muted-foreground)]">
          {t("Still loading…")}
        </p>
      ) : null}
    </div>
  );
}

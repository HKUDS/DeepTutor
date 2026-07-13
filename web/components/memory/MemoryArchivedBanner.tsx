"use client";

import { useCallback, useState } from "react";
import { Archive, ChevronDown, ChevronUp, X } from "lucide-react";
import { useTranslation } from "react-i18next";

const STORAGE_KEY = "dt:memory:banner-dismissed";

interface MemoryArchivedBannerProps {
  latestBackup: string | null;
  variant?: "full" | "compact";
}

export default function MemoryArchivedBanner({
  latestBackup,
  variant = "compact",
}: MemoryArchivedBannerProps) {
  const { t } = useTranslation();
  const [dismissed, setDismissed] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(STORAGE_KEY);
  });
  const [expanded, setExpanded] = useState(false);

  const dismiss = useCallback(() => {
    if (!latestBackup) return;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, latestBackup);
    }
    setDismissed(latestBackup);
  }, [latestBackup]);

  if (!latestBackup || dismissed === latestBackup) return null;

  if (variant === "full") {
    return (
      <div className="relative flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--muted)] px-5 py-4 pr-12 text-[13px]">
        <Archive className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
        <div>
          <p className="font-medium text-[var(--foreground)]">
            {t("Your v1 memory was archived")}
          </p>
          <p className="mt-0.5 text-[var(--muted-foreground)]">
            {t(
              "Stored at memory/backup/{{name}}. v2 starts fresh — interact with DeepTutor and click Update on each doc to build memory.",
              { name: latestBackup },
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label={t("Dismiss")}
          className="absolute right-2 top-2 rounded-md p-1.5 text-[var(--muted-foreground)] transition hover:bg-[var(--background)] hover:text-[var(--foreground)]"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--muted)]/60 text-[12px]">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-4 py-2 text-left"
      >
        <span className="flex items-center gap-2 text-[var(--muted-foreground)]">
          <Archive className="h-3.5 w-3.5" />
          {t("Your v1 memory was archived")}
        </span>
        {expanded ? (
          <ChevronUp className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
        )}
      </button>
      {expanded && (
        <div className="relative border-t border-[var(--border)] px-4 py-3 pr-10 text-[var(--muted-foreground)]">
          {t(
            "Stored at memory/backup/{{name}}. v2 starts fresh — interact with DeepTutor and click Update on each doc to build memory.",
            { name: latestBackup },
          )}
          <button
            type="button"
            onClick={dismiss}
            aria-label={t("Dismiss")}
            className="absolute right-2 top-2 rounded-md p-1 text-[var(--muted-foreground)] transition hover:bg-[var(--background)] hover:text-[var(--foreground)]"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}
    </div>
  );
}

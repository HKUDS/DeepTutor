"use client";

import { Loader2, Rocket, Save, Wand2 } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import { storagePathFor } from "@/lib/settings-nav";
import { useSettings } from "./SettingsContext";

// Sticky toolbar above the sub-page content. Save Draft / Apply only show
// when there's actually something to save — keeps the bar quiet for the
// majority of sessions that just visit Appearance.
export function SettingsToolbar() {
  const { t } = useTranslation();
  const pathname = usePathname() ?? "";
  const storagePath = storagePathFor(pathname);
  const {
    catalogEditable,
    hasUnsavedChanges,
    saving,
    applying,
    saveCatalog,
    applyCatalog,
    startTour,
    toast,
  } = useSettings();

  if (catalogEditable !== true) {
    if (!toast) return null;
    return (
      <div className="flex items-center justify-end px-1 py-2">
        <p className="text-[12px] text-[var(--primary)] animate-fade-in">
          {toast}
        </p>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between gap-3 px-1 py-2">
      <p
        className={`min-w-0 truncate text-[12px] ${
          toast
            ? "text-[var(--primary)] animate-fade-in"
            : hasUnsavedChanges
              ? "text-amber-600 dark:text-amber-400"
              : "text-[var(--muted-foreground)]"
        }`}
      >
        {toast ? (
          toast
        ) : hasUnsavedChanges ? (
          t("Draft has unsaved changes")
        ) : storagePath ? (
          <>
            {t("Saved to")}{" "}
            <span className="font-mono text-[var(--foreground)]/65">
              {storagePath}
            </span>
          </>
        ) : (
          t("All changes saved")
        )}
      </p>
      <div className="flex items-center gap-2">
        <button
          onClick={startTour}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
        >
          <Rocket className="h-3 w-3" />
          {t("Tour")}
        </button>
        <button
          onClick={saveCatalog}
          disabled={saving || !hasUnsavedChanges}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Save className="h-3 w-3" />
          )}
          {t("Save Draft")}
        </button>
        <button
          data-tour="tour-actions"
          onClick={applyCatalog}
          disabled={applying}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80 disabled:opacity-40"
        >
          {applying ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Wand2 className="h-3 w-3" />
          )}
          {t("Apply")}
        </button>
      </div>
    </div>
  );
}

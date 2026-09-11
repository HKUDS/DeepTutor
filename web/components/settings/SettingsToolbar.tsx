"use client";

import { Loader2, Rocket, Save, Undo2, Wand2 } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import { storagePathFor } from "@/features/settings/navigation/settings-nav";
import { useSettings } from "@/features/settings/store/SettingsStore";

/**
 * Sticky toolbar above the sub-page content.
 *
 * Save Draft and Apply now promise different things and the bar has to say
 * which state you are in, because "there is a draft waiting" is invisible
 * otherwise — a draft parked yesterday would sit there unexplained.
 *
 *   unsaved edits   → Save draft · Apply         ("Unsaved changes")
 *   draft on server → Apply · Discard            ("Draft not applied yet")
 *   neither         → nothing to do              ("All changes saved")
 *
 * The storage path moved into the status line's tooltip: self-hosted users
 * occasionally want to know which file backs a page, but it is a developer
 * fact and does not belong permanently on screen for everyone else.
 */
export function SettingsToolbar() {
  const { t } = useTranslation();
  const pathname = usePathname() ?? "";
  const {
    catalogEditable,
    draftState,
    saving,
    applying,
    saveDraft,
    applyCatalog,
    discardDraft,
    startTour,
    toast,
    activeSection,
  } = useSettings();
  const storagePath = storagePathFor(pathname, activeSection);

  const busy = saving || applying;
  const canApply = draftState !== "clean";

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

  const status = toast
    ? { text: toast, tone: "text-[var(--primary)] animate-fade-in" }
    : draftState === "unsaved"
      ? {
          text: t("Unsaved changes"),
          tone: "text-amber-600 dark:text-amber-400",
        }
      : draftState === "saved"
        ? {
            text: t("Draft not applied yet"),
            tone: "text-amber-600 dark:text-amber-400",
          }
        : {
            text: t("All changes saved"),
            tone: "text-[var(--muted-foreground)]",
          };

  return (
    <div className="flex flex-col items-stretch gap-2 px-1 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
      <p
        className={`min-w-0 truncate text-[12px] ${status.tone}`}
        title={storagePath || undefined}
      >
        {status.text}
      </p>
      <div className="flex shrink-0 items-center justify-end gap-2">
        <button
          onClick={startTour}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
        >
          <Rocket className="h-3 w-3" />
          <span className="max-sm:hidden">{t("Tour")}</span>
        </button>
        {canApply && (
          <button
            onClick={discardDraft}
            disabled={busy}
            title={t("Go back to what is currently live.")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
          >
            <Undo2 className="h-3 w-3" />
            <span className="max-sm:hidden">{t("Discard")}</span>
          </button>
        )}
        <button
          onClick={saveDraft}
          disabled={busy || draftState !== "unsaved"}
          title={t("Store these changes without putting them into effect.")}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/50 px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Save className="h-3 w-3" />
          )}
          <span className="max-sm:hidden">{t("Save draft")}</span>
        </button>
        <button
          data-tour="tour-actions"
          onClick={applyCatalog}
          disabled={busy || !canApply}
          title={t("Put these settings into effect.")}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80 disabled:opacity-40"
        >
          {applying ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Wand2 className="h-3 w-3" />
          )}
          <span className="max-sm:hidden">{t("Apply")}</span>
        </button>
      </div>
    </div>
  );
}

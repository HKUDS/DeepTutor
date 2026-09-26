"use client";

import { Loader2, Save, Undo2, Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSettings } from "@/features/settings/store/SettingsStore";

/** A single, explicit save surface, visible only when there is work to do. */
export function SettingsToolbar() {
  const { t } = useTranslation();
  const {
    draftState,
    saving,
    applying,
    saveDraft,
    applyCatalog,
    discardDraft,
    toast,
  } = useSettings();
  const busy = saving || applying;
  if (draftState === "clean")
    return toast ? (
      <div
        role="status"
        className="shrink-0 border-t border-[color-mix(in_srgb,var(--border)_50%,transparent)] px-5 py-3 text-center text-xs text-[var(--muted-foreground)]"
      >
        {toast}
      </div>
    ) : null;
  return (
    <div
      data-tour="tour-actions"
      className="shrink-0 border-t border-[var(--border)] bg-[var(--background)] px-5 py-3 sm:px-8"
    >
      <div className="mx-auto flex max-w-[calc(var(--settings-content,960px)_-_7rem)] flex-wrap items-center justify-between gap-3">
        <div className="min-w-0" role="status">
          <p className="text-[13px] font-medium">
            {draftState === "saved"
              ? t("Draft not applied yet")
              : t("Unsaved changes")}
          </p>
          <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
            {toast || t("Applies pending changes across all settings pages.")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={discardDraft}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
          >
            <Undo2 size={14} />
            {t("Discard")}
          </button>
          <button
            type="button"
            onClick={() => void saveDraft()}
            disabled={busy || draftState !== "unsaved"}
            title={t("Store these changes without putting them into effect.")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-40"
          >
            {saving ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Save size={14} />
            )}
            {t("Save draft")}
          </button>
          <button
            type="button"
            onClick={applyCatalog}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-2 text-xs font-medium text-[var(--background)] disabled:opacity-40"
          >
            {applying ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Check size={14} />
            )}
            {t("Apply changes")}
          </button>
        </div>
      </div>
    </div>
  );
}

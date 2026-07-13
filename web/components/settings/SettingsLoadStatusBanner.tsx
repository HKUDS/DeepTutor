"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSettings } from "./SettingsContext";

// Surface the result of the initial /api/v1/settings + /api/v1/system/status
// load so Docker / first-run users know *why* the page is empty when the
// backend is unreachable, instead of seeing a blank screen with the failure
// only in the dev console.
export function SettingsLoadStatusBanner() {
  const { t } = useTranslation();
  const { settingsLoading, settingsError, reloadSettings } = useSettings();
  const [retrying, setRetrying] = useState(false);

  if (settingsLoading) {
    return (
      <div className="mt-3 flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-sm text-[var(--foreground-soft)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("Loading settings...")}
      </div>
    );
  }

  if (!settingsError) return null;

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await reloadSettings();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div
      role="alert"
      className="mt-3 flex items-start gap-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">
          {t("Could not load settings from the backend.")}
        </div>
        <div className="mt-1 text-xs opacity-90">{settingsError}</div>
        <div className="mt-1 text-xs opacity-75">
          {t(
            "Verify the backend is running and NEXT_PUBLIC_API_BASE points to a reachable host. For Docker, see data/user/settings/system.json.",
          )}
        </div>
      </div>
      <button
        type="button"
        onClick={handleRetry}
        disabled={retrying}
        className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-100 px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-200 disabled:opacity-60 dark:border-amber-500/40 dark:bg-amber-500/20 dark:text-amber-100"
      >
        <RefreshCw className={retrying ? "h-3 w-3 animate-spin" : "h-3 w-3"} />
        {t("Retry")}
      </button>
    </div>
  );
}

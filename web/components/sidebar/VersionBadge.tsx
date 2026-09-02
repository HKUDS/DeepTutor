"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import {
  fetchAppUpdateStatus,
  subscribeAppUpdateStatus,
  type AppUpdateStatus,
} from "@/lib/app-update";
import { normalizeVersionTag } from "@/lib/version";
import {
  requestSettingsSection,
  scrollToSettingsSection,
} from "@/features/settings/navigation/settings-scroll";

interface VersionBadgeProps {
  /** Render the compact variant for the collapsed sidebar (currently hidden). */
  collapsed?: boolean;
}

export function VersionBadge({ collapsed = false }: VersionBadgeProps) {
  const { t } = useTranslation();
  const pathname = usePathname();
  const [status, setStatus] = useState<AppUpdateStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const unsubscribe = subscribeAppUpdateStatus((signal) => {
      if (!active) return;
      if (signal.status) setStatus(signal.status);
      setError(signal.error);
    });

    void fetchAppUpdateStatus(controller.signal).catch((cause) => {
      if (!active || controller.signal.aborted) return;
      setError(
        cause instanceof Error ? cause.message : "Unable to check for updates",
      );
    });

    return () => {
      active = false;
      controller.abort();
      unsubscribe();
    };
  }, []);

  // Keep the collapsed sidebar entirely free of version chrome.
  if (collapsed) return null;

  const tag =
    normalizeVersionTag(status?.current_version) ??
    normalizeVersionTag(process.env.NEXT_PUBLIC_APP_VERSION || "");
  const displayTag = tag ?? "—";
  const state = error
    ? { dot: "bg-red-500", label: t("Status check failed") }
    : status?.update_available
      ? { dot: "bg-amber-500", label: t("Update available") }
      : status?.release
        ? { dot: "bg-emerald-500", label: t("Up to date") }
        : status && !status.check_enabled
          ? {
              dot: "bg-[var(--muted-foreground)]/35",
              label: t("Version checks are disabled."),
            }
          : {
              dot: "bg-[var(--muted-foreground)]/35",
              label: status ? t("Not checked yet") : t("Checking..."),
            };

  return (
    <Link
      href="/settings#about"
      scroll={false}
      onClick={(event) => {
        if (pathname !== "/settings") return;
        event.preventDefault();
        window.history.replaceState(null, "", "/settings#about");
        scrollToSettingsSection("about", "auto");
        requestSettingsSection("about");
      }}
      title={`${displayTag} · ${state.label}`}
      aria-label={`${displayTag} · ${state.label}`}
      className="group/ver flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-1.5 font-serif text-[14px] font-semibold tabular-nums tracking-[-0.025em] text-[var(--foreground)]/80 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 shrink-0 rounded-full transition-colors ${state.dot}`}
      />
      <span className="truncate leading-none decoration-[var(--muted-foreground)]/40 decoration-dotted underline-offset-[3px] group-hover/ver:underline">
        {displayTag}
      </span>
    </Link>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useState, type MouseEventHandler } from "react";
import { useTranslation } from "react-i18next";

import {
  fetchAppUpdateStatus,
  subscribeAppUpdateStatus,
  type AppUpdateStatus,
} from "@/lib/app-update";

interface VersionBadgeProps {
  onNavigate?: MouseEventHandler<HTMLAnchorElement>;
}

export function VersionBadge({ onNavigate }: VersionBadgeProps) {
  const { t } = useTranslation();
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

  const state = error
    ? { dot: "bg-red-500", label: t("Status check failed") }
    : status?.update_available
      ? { dot: "bg-amber-500", label: t("Update available") }
      : status?.release
        ? {
            dot: "bg-[color-mix(in_srgb,var(--muted-foreground)_35%,transparent)]",
            label: t("Up to date"),
          }
        : status && !status.check_enabled
          ? {
              dot: "bg-[color-mix(in_srgb,var(--muted-foreground)_35%,transparent)]",
              label: t("Version checks are disabled."),
            }
          : {
              dot: "bg-[color-mix(in_srgb,var(--muted-foreground)_35%,transparent)]",
              label: status ? t("Not checked yet") : t("Checking..."),
            };

  return (
    <Link
      href="/settings/about"
      onClick={onNavigate}
      title={state.label as string}
      aria-label={state.label as string}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-background/50 hover:text-[var(--foreground)]"
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 rounded-full transition-colors ${state.dot}`}
      />
    </Link>
  );
}

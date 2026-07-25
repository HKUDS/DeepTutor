"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchUpdateStatus } from "@/lib/update-api";
import {
  presentUpdateBadge,
  type UpdateBadgePresentation,
} from "@/lib/update-badge";
import { normalizeVersionTag } from "@/lib/version";

interface VersionBadgeProps {
  /** Render the compact variant for the collapsed sidebar (currently hidden). */
  collapsed?: boolean;
}

const RELEASES_URL = "https://github.com/HKUDS/DeepTutor/releases";

export function VersionBadge({ collapsed = false }: VersionBadgeProps) {
  const { t } = useTranslation();
  const [update, setUpdate] = useState<UpdateBadgePresentation | null>(null);

  useEffect(() => {
    if (collapsed) return;

    const controller = new AbortController();
    void fetchUpdateStatus(controller.signal)
      .then((result) => setUpdate(presentUpdateBadge(result)))
      .catch(() => {
        if (!controller.signal.aborted) setUpdate({ kind: "failed" });
      });
    return () => controller.abort();
  }, [collapsed]);

  // Keep the collapsed sidebar entirely free of version chrome.
  if (collapsed) return null;

  const upToDate = update?.kind === "up_to_date" ? update : null;
  const tag = normalizeVersionTag(process.env.NEXT_PUBLIC_APP_VERSION || "");
  const fallbackTag = upToDate?.version ?? null;
  const displayTag = tag ?? fallbackTag ?? "—";
  const available = update?.kind === "available" ? update : null;
  let statusText: string;
  if (available?.hostManaged) statusText = t("Update on host") as string;
  else if (available) statusText = t("Update available") as string;
  else if (update === null) statusText = t("Checking for updates…") as string;
  else if (update.kind === "up_to_date") statusText = t("Up to date") as string;
  else statusText = t("Update check failed") as string;
  const title = available?.hostManaged
    ? (t(
        "Update the image on the Docker host and recreate the container.",
      ) as string)
    : available
      ? (t("Latest release") as string)
      : statusText;
  const ariaLabel = available
    ? `${statusText}: ${displayTag} → ${available.version}. ${t("Latest release") as string}`
    : `${displayTag}. ${statusText}`;

  return (
    <div
      data-testid="version-badge"
      aria-live="polite"
      aria-atomic="true"
      className="flex min-w-0 flex-1"
    >
      <a
        data-testid="update-status"
        href={available?.href ?? upToDate?.href ?? RELEASES_URL}
        target="_blank"
        rel="noreferrer noopener"
        title={title}
        aria-label={ariaLabel}
        className="group/ver flex min-w-0 flex-1 items-center gap-1 rounded-lg px-3 py-1.5 text-[11px] font-mono tracking-tight text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]"
      >
        <span className="shrink-0 leading-none decoration-[var(--muted-foreground)]/40 decoration-dotted underline-offset-[3px] group-hover/ver:underline">
          {displayTag}
        </span>
        {available ? (
          <>
            <span aria-hidden="true" className="shrink-0 opacity-55">
              →
            </span>
            <span className="shrink-0 leading-none text-sky-600 dark:text-sky-400">
              {available.version}
            </span>
            {available.hostManaged ? (
              <span className="truncate leading-none">· {statusText}</span>
            ) : null}
          </>
        ) : (
          <span className="truncate leading-none">· {statusText}</span>
        )}
      </a>
    </div>
  );
}

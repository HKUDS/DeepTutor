"use client";

import { normalizeVersionTag } from "@/lib/version";

interface VersionBadgeProps {
  /** Render the compact variant for the collapsed sidebar (currently hidden). */
  collapsed?: boolean;
}

const RELEASES_URL = "https://github.com/HKUDS/DeepTutor/releases";

export function VersionBadge({ collapsed = false }: VersionBadgeProps) {
  // Keep the collapsed sidebar entirely free of version chrome.
  if (collapsed) return null;

  const tag = normalizeVersionTag(process.env.NEXT_PUBLIC_APP_VERSION || "");
  const displayTag = tag ?? "—";

  return (
    <a
      href={RELEASES_URL}
      target="_blank"
      rel="noreferrer noopener"
      title={displayTag}
      className="group/ver flex min-w-0 flex-1 items-center rounded-lg px-3 py-1.5 text-[11px] font-mono tabular-nums tracking-tight text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]"
    >
      <span className="truncate leading-none decoration-[var(--muted-foreground)]/40 decoration-dotted underline-offset-[3px] group-hover/ver:underline">
        {displayTag}
      </span>
    </a>
  );
}

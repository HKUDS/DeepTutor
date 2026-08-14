"use client";

import { normalizeVersionTag } from "@/lib/version";

interface VersionBadgeProps {
  /** Render the compact variant for the collapsed sidebar (currently hidden). */
  collapsed?: boolean;
}

export function VersionBadge({ collapsed = false }: VersionBadgeProps) {
  // Keep the collapsed sidebar entirely free of version chrome.
  if (collapsed) return null;

  const tag = normalizeVersionTag(process.env.NEXT_PUBLIC_APP_VERSION || "");
  const displayTag = tag ?? "—";

  return (
    <span
      title={displayTag}
      className="flex min-w-0 flex-1 items-center rounded-lg px-3 py-1.5 text-[11px] font-mono tabular-nums tracking-tight text-[var(--muted-foreground)]/55"
    >
      <span className="truncate leading-none">{displayTag}</span>
    </span>
  );
}

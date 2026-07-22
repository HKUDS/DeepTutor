"use client";

import type { ReactNode } from "react";

/**
 * Instant CSS tooltip — replaces the native `title` attribute, whose
 * ~1s OS-controlled hover delay makes icon-only buttons feel
 * unresponsive. Fades in after a ~150ms hover-intent delay and also
 * shows on keyboard focus. Pure CSS (group-hover, no portal), so
 * callers should avoid mounting it flush against an overflow-hidden
 * edge where the label would clip.
 */
export default function Tooltip({
  label,
  side = "bottom",
  children,
}: {
  label: string;
  /** Which side of the trigger the label appears on. */
  side?: "top" | "bottom";
  children: ReactNode;
}) {
  const place = side === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";
  return (
    <span className="group/tip relative inline-flex">
      {children}
      <span
        role="tooltip"
        aria-hidden
        className={`pointer-events-none absolute left-1/2 z-[80] -translate-x-1/2 ${place} whitespace-nowrap rounded-md bg-[var(--foreground)] px-2 py-1 text-[11px] font-medium leading-none text-[var(--background)] opacity-0 shadow-md transition-opacity duration-100 group-focus-within/tip:opacity-100 group-hover/tip:opacity-100 group-hover/tip:delay-150`}
      >
        {label}
      </span>
    </span>
  );
}

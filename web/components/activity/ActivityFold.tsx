"use client";

import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";

/**
 * One curve and one duration for every disclosure in the activity
 * vocabulary, so a header and the fold hanging from it settle on the same
 * beat. The curve is the fast-out/long-settle shape the sidebar's "More"
 * disclosure uses — crisper than `ease-out` at this size.
 *
 * Reduced motion needs no opt-out here: `globals.css` shortens every
 * transition to a near-imperceptible duration under that setting.
 */
export const FOLD_EASE = "duration-[220ms] ease-[cubic-bezier(0.32,0.72,0,1)]";

/**
 * The caret that says a line is a disclosure.
 *
 * Kept at the same weight as the metadata beside it ("· 33s · 4 tool calls"):
 * on a line that is mostly read and occasionally clicked, the caret is there
 * to promise the content is recoverable, not to ask to be pressed. It lifts
 * to full contrast with the rest of the line on hover.
 */
export function FoldCaret({ open }: { open: boolean }) {
  return (
    <ChevronRight
      aria-hidden
      className={`size-3 shrink-0 text-[var(--muted-foreground)]/45 transition-[transform,color] group-hover/act:text-current ${FOLD_EASE} ${
        open ? "rotate-90" : ""
      }`}
    />
  );
}

/**
 * Content that folds away without being unmounted.
 *
 * Animates on `grid-template-rows` between `0fr` and `1fr`, which is the one
 * way to transition to a height the content decides — no measuring, no
 * `max-height` guess that either clips a long trace or makes a short one
 * crawl open.
 */
export function ActivityFold({
  open,
  children,
  className = "",
}: {
  open: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`grid transition-[grid-template-rows,opacity] ${FOLD_EASE} ${
        open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
      } ${className}`}
    >
      <div className="overflow-hidden">{children}</div>
    </div>
  );
}

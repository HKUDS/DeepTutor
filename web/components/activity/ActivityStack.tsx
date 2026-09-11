"use client";

import type { ReactNode } from "react";

/**
 * The container for a run of {@link ActivityRow}s.
 *
 * Its job is the two-column grid: every row's mark column lands under the
 * orb of whatever header sits above the stack, so marks share one column and
 * text shares another. The predecessor indented the rows 24px and drew a rule
 * down the gap — an indent *and* an axis, both saying "these belong to the
 * header". Aligning instead makes the whole block read as one grid, and lets
 * hierarchy come from the marks themselves (a cloud of dots for the header,
 * a single dot per row), which is stronger than whitespace.
 */
export function ActivityStack({
  children,
  alignUnderOrb = true,
  className = "",
}: {
  children: ReactNode;
  /**
   * Offset the mark column to sit under an 18px orb. 2px is what centres a
   * 15px dot column beneath it. Turn off for stacks with no orb above them.
   */
  alignUnderOrb?: boolean;
  className?: string;
}) {
  return (
    <div
      // 1px, not 3. Consecutive rows should pack tighter than body text so
      // the block reads as an aside rather than as prose — the status dots
      // already separate the lines, so the gap only has to keep them from
      // touching.
      className={`space-y-px ${alignUnderOrb ? "ml-[2px]" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * A labelled divider between groups of rows — a solve step, a book chapter.
 *
 * A group is a divider, not a level. Making it a third fold (which is what
 * chat's "Step N" used to be, complete with its own separate renderer) put
 * the rows two levels deeper than their siblings for no gain: the reader
 * still has to open the fold to see anything, so the fold only ever cost a
 * click. Labelling the group and leaving its rows at level one keeps every
 * row in a turn reading and folding the same way.
 */
export function ActivityDivider({
  label,
  active = false,
  className = "",
}: {
  label: ReactNode;
  /** Breathe the label while this group is the one being worked on. */
  active?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`flex items-center gap-2 py-1 text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--muted-foreground)]/45 ${className}`}
    >
      <span className={active ? "dt-breathing-text" : ""}>{label}</span>
      <span className="h-px flex-1 bg-[var(--border)]/25" />
    </div>
  );
}

"use client";

import type { ReactNode } from "react";

import { ActivityOrb, type OrbState } from "./ActivityOrb";

/**
 * The header above a stack of activity rows: an orb, what is happening, and
 * how long it has been happening.
 *
 * The orb is the only place a *cloud* of dots appears; every row below shows
 * a single one. That contrast is what carries the hierarchy, which is why the
 * stack needs neither an indent nor a rule to belong to this line.
 *
 * Doubles as the stack's disclosure control when `expandable`, with no
 * chevron: the row's hover colour shift is the only affordance, because a
 * permanent chevron on a line that is mostly read, not clicked, is noise.
 */
export function ActivityHeader({
  orb,
  orbSpeed = 1,
  label,
  duration,
  settled = false,
  expandable = false,
  expanded = false,
  onToggle,
  showOrb = true,
  className = "",
}: {
  /** Which orb animation names the current phase. */
  orb: OrbState;
  /** Below 1 for a resting phase — see the `responded` case in chat. */
  orbSpeed?: number;
  label: ReactNode;
  /** Elapsed time, already formatted. */
  duration?: string | null;
  /** Stop breathing the label and dim it: the work is over. */
  settled?: boolean;
  expandable?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  /** Hide the orb where an avatar already signals who is working. */
  showOrb?: boolean;
  className?: string;
}) {
  const breathing = settled ? "" : "dt-breathing-text";
  const textColor = settled
    ? "text-[var(--muted-foreground)]/70"
    : "text-[var(--muted-foreground)]";

  const inner = (
    <>
      {showOrb ? <ActivityOrb state={orb} speed={orbSpeed} /> : null}
      <span className={breathing}>{label}</span>
      {duration ? (
        <span className="text-[12px] font-medium tabular-nums text-[var(--muted-foreground)]/55">
          · {duration}
        </span>
      ) : null}
    </>
  );

  const shared = `flex items-center gap-2.5 text-[14px] font-semibold leading-none ${textColor} ${className}`;

  if (expandable) {
    return (
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-live="polite"
        className={`group/act w-full text-left transition-colors hover:text-[var(--foreground)] ${shared}`}
      >
        {inner}
      </button>
    );
  }

  // `aria-live="polite"` surfaces phase transitions to screen readers
  // without barging in on the user.
  return (
    <div role="status" aria-live="polite" aria-atomic="false" className={shared}>
      {inner}
    </div>
  );
}

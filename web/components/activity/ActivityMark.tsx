"use client";

import { ActivityOrb } from "./ActivityOrb";
import type { ActivityState } from "./types";

/**
 * A list row's mark: a live thought-orb while it works, a settled ring once
 * it stops.
 *
 * The list counterpart of {@link StatusDot}. A dot is right inside a stack of
 * activity rows, where a header orb sits above it in the same column and the
 * contrast between cloud and dot carries the hierarchy. A list of the
 * reader's own things — sessions, chapters — has no orb above it, so each row
 * has only its own mark to say whether it is running, and a 5px dot cannot
 * carry that on its own.
 *
 * Both forms are always mounted and cross-faded, because a conditional
 * cannot be animated and the contraction *is* the signal: a chapter
 * finishing reads as its orb condensing into the ring rather than as one
 * mark being swapped for another.
 *
 * `SessionAvatar` is the same idea with session-specific semantics on top
 * (unread and failed each get their own fill and hue, and the priority
 * between them matters). This is the plain four-state version for everything
 * else.
 */

/** The ring's diameter as a fraction of the box — matched to `SessionAvatar`. */
const RING_RATIO = 0.58;

/**
 * Calmer than the trace orbs and than a status header's.
 *
 * A 12px mark in a list of twenty rows has only its motion to say "this one
 * is running", but at the harness's 1.6 it read as agitated.
 */
const LIVE_SPEED = 1.3;

/**
 * The resting form: one circle, hollow or filled.
 *
 * SVG rather than a CSS-bordered box. A 1px CSS border is two device pixels
 * on a retina screen and cannot go thinner, which on a 7px circle is a heavy
 * outline; an SVG stroke scales with the viewBox and can stay hairline.
 */
function SettledRing({
  size,
  state,
  tone,
}: {
  size: number;
  state: ActivityState;
  tone: MarkTone;
}) {
  // Solid and blue for work that produced something, hollow and grey for
  // work that has not started. Same element, same diameter — only the fill
  // and the hue change, so moving between them animates rather than
  // flickering one shape out for another of the same size.
  const done = state !== "error" && state !== "awaiting";
  const filled = state === "error" || (done && tone === "accent");
  const ink =
    state === "error"
      ? "text-[var(--destructive)] opacity-100"
      : state === "awaiting"
        ? "text-[var(--warning)] opacity-100"
        : tone === "accent"
          ? "text-blue-600 opacity-100 dark:text-blue-400"
          : "text-[var(--muted-foreground)] opacity-45 group-hover/mark:opacity-75";
  return (
    <svg
      viewBox="0 0 12 12"
      width={size}
      height={size}
      className={`transition-[color,opacity] duration-300 ease-out ${ink}`}
    >
      <circle
        cx="6"
        cy="6"
        r="5.1"
        stroke="currentColor"
        strokeWidth="1.25"
        className={`transition-[fill] duration-300 ease-out ${
          filled ? "fill-current" : "fill-transparent"
        }`}
      />
    </svg>
  );
}

/**
 * Which settled mark a finished row gets.
 *
 * `muted` is the default: a hollow grey ring for work that has not happened.
 * `accent` is for work that finished *and left something behind* — a written
 * chapter, a delivered answer — which a reader scans for and which a grey
 * ring cannot distinguish from "not started yet".
 */
export type MarkTone = "muted" | "accent";

export function ActivityMark({
  state,
  size = 12,
  tone = "muted",
  className = "",
}: {
  state: ActivityState;
  size?: number;
  tone?: MarkTone;
  className?: string;
}) {
  const running = state === "running";
  return (
    <span
      className={`group/mark relative inline-flex shrink-0 items-center justify-center ${className}`}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <span
        className={`absolute inset-0 flex items-center justify-center transition-[opacity,transform] duration-300 ease-out ${
          running ? "scale-100 opacity-100" : "scale-[0.45] opacity-0"
        }`}
      >
        <ActivityOrb
          state="composing"
          speed={LIVE_SPEED}
          box={size}
          tone="live"
        />
      </span>
      <span
        className={`absolute inset-0 flex items-center justify-center transition-[opacity,transform] duration-300 ease-out ${
          running ? "scale-[1.55] opacity-0" : "scale-100 opacity-100"
        }`}
      >
        <SettledRing
          size={Math.round(size * RING_RATIO)}
          state={state}
          tone={tone}
        />
      </span>
    </span>
  );
}

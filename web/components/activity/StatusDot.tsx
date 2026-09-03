"use client";

import type { ActivityState } from "./types";

/**
 * The leading status dot for one line of activity.
 *
 * This is the whole icon vocabulary for activity rows. It replaced a family
 * of thirteen hand-drawn semantic glyphs, for two reasons that hold on every
 * surface, not just chat: the row's own text already names *what* is
 * happening ("Perplexity 联网搜索 …", "编译第 3 章"), so a glyph restating the
 * category spent the row's only pre-text position on information already in
 * view; and at 15px a multi-stroke mark reads as a smaller, muddier version
 * of the thought-orb sitting above it in the same column.
 *
 * What the text cannot say is where the step *stands*. So the dot says that,
 * and one small mark reads as a single atom of the orb's dot cloud rather
 * than as a rival to it.
 */
export function StatusDot({
  state,
  className = "",
}: {
  state: ActivityState;
  className?: string;
}) {
  // Running is blue rather than `--primary`. Primary is the brand hue and
  // shifts per theme (warm orange on dark, violet on glass); "in flight"
  // should be the same signal colour everywhere, and has to stay clearly
  // apart from the amber and red states — warm orange beside red does not.
  //
  // Alpha rides on `opacity-*`, never on Tailwind's `/NN` colour modifier:
  // against an arbitrary `var()` colour that modifier compiles to nothing and
  // the dot renders fully transparent.
  const tone =
    state === "error"
      ? "bg-[var(--destructive)]"
      : state === "awaiting"
        ? "bg-[var(--warning)]"
        : state === "running"
          ? "bg-blue-600 dark:bg-blue-400"
          : "bg-[var(--muted-foreground)] opacity-40 group-hover/row:opacity-70";

  return (
    // The fixed 15px box is the mark column: it keeps text baselines aligned
    // across rows and absorbs the running dot's scale-up, so a pulsing row
    // never nudges its own label.
    <span
      className={`flex h-[15px] w-[15px] shrink-0 items-center justify-center ${className}`}
    >
      <span
        className={`h-[5px] w-[5px] rounded-full transition-colors ${tone} ${
          state === "running" ? "dt-dot-live" : ""
        }`}
      />
    </span>
  );
}

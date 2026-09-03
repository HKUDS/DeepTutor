"use client";

import { usePickerOpen } from "@/hooks/usePickerOpen";
import { ThinkingOrb, type OrbState } from "@/vendor/thinking-orbs";

export type { OrbState };

/**
 * The preset to resolve, and the box to paint it in.
 *
 * These differ on purpose. 20 is the only small preset upstream ships and it
 * carries its own dot count, dot radius and speed — so that is what gets
 * resolved. But ink covers most of the box, which at 20 put the mark around
 * 16px against a 14px label's 9.94px cap height: 1.6x the type, where an
 * inline glyph normally sits at 1.0–1.25x. An 18px box pulls it back without
 * shrinking the dots into noise.
 */
const ORB_PRESET = 20;
const ORB_BOX = 18;

/**
 * Supersampling needed to keep dots solid at a given box size.
 *
 * The dot radius scales with the box, so a smaller box needs a
 * *proportionally larger* bitmap just to hold the same physical dot size —
 * shrinking the box without raising this is how you get the smudge the
 * inline orbs started out with. 3 is measured for the 18px default (see
 * below); anything tighter than 16px gets a step more.
 */
function superSampleFor(box: number): number {
  return box < 16 ? 4 : 3;
}

/**
 * Bitmap resolution multiplier — see `superSample` in the vendored copy.
 *
 * Upstream caps the canvas at `min(2, dpr) x size`, so a 20px orb gets a
 * 40x40 bitmap: each dot lands under a pixel wide and `arc()` antialiasing
 * smears it over two or three, which beside hinted type reads as a smudge
 * rather than a dot.
 *
 * 3 is measured, not guessed. Counting alpha across the ink at each
 * multiplier, upstream leaves 57% of its ink pixels at mid alpha — over half
 * the "dots" being antialiasing — against 32% solid. 2x flips that to 59%
 * solid, 3x peaks at 67%, and 4x falls back to 64%: past the knee the dots
 * are wide enough that their own circumference adds more transition pixels
 * than the sharper core removes.
 */
const ORB_SUPERSAMPLE = 3;

/**
 * Which ink an orb draws in.
 *
 * `brand` is the default and follows `--primary`, which is right for a status
 * header speaking for the product. `live` is the same blue the status dots
 * use for work in flight — for orbs that mean "this is running *now*" rather
 * than "this is DeepTutor thinking", where the signal has to read the same
 * on every theme.
 */
export type OrbTone = "brand" | "live";

/**
 * A thought-orb at DeepTutor's house settings.
 *
 * Every surface that shows one goes through here, so the size, resolution,
 * ink and pause behaviour cannot drift between chat, books and the rest.
 *
 * Two things this handles that the vendored component cannot: the ink comes
 * from `currentColor` (hence the colour class, not a prop), and the
 * picker-open freeze is wired by hand because `animation-play-state` cannot
 * reach a canvas rAF loop.
 */
export function ActivityOrb({
  state,
  speed = 1,
  box = ORB_BOX,
  tone = "brand",
  className = "",
}: {
  state: OrbState;
  /** Multiplier on the preset's own speed. Below 1 for resting states. */
  speed?: number;
  /** CSS box to paint into. Defaults to the tuned inline size. */
  box?: number;
  tone?: OrbTone;
  className?: string;
}) {
  const pickerOpen = usePickerOpen();

  return (
    <ThinkingOrb
      state={state}
      size={ORB_PRESET}
      style={{ width: box, height: box }}
      superSample={
        box === ORB_BOX ? ORB_SUPERSAMPLE : superSampleFor(box)
      }
      speed={speed}
      paused={pickerOpen}
      // Callers pair the orb with a live region that spells the phase out in
      // words; the orb is the decorative half of that.
      aria-hidden
      className={`shrink-0 ${
        tone === "live"
          ? "text-blue-600 dark:text-blue-400"
          : "text-[var(--primary)]"
      } ${className}`}
    />
  );
}

/**
 * Geometry of the reader/chat split.
 *
 * Pure so the boundary arithmetic — the part that is easy to get wrong and
 * invisible when it is — can be tested without a DOM. The component that drags
 * the seam only measures and writes; every decision about *what* width is
 * allowed happens here.
 */

/** Narrow enough to be useless as a reader below this. */
export const READER_MIN_PX = 360;
/** Always leave the conversation at least this much. */
export const CHAT_MIN_PX = 380;
/** No reason to go wider than this even on a huge display. */
export const READER_MAX_PX = 1400;
/** Arrow-key step; Shift multiplies it. */
export const READER_STEP_PX = 24;

/** CSS custom property both sides of the split read. */
export const READER_WIDTH_VAR = "--reader-width";
/** localStorage key for the user's chosen width. */
export const READER_WIDTH_KEY = "dt.reader.width";

/**
 * Clamp a candidate reader width so neither side can be squeezed out of use.
 *
 * `available` is the width of the box the two panes share. When it is unknown
 * (server render, or a measurement taken before layout) only the absolute
 * bounds apply — the CSS carries its own percentage ceiling for that case, so a
 * stored pixel value can never paint over the conversation either way.
 *
 * The floor wins over the ceiling on a genuinely narrow container: a reader
 * clamped to 40px would be worse than one that overflows slightly, and below
 * `lg` the split does not exist at all.
 */
export function clampReaderWidth(px: number, available: number): number {
  if (!Number.isFinite(px)) return READER_MIN_PX;
  const ceiling =
    available > 0
      ? Math.min(READER_MAX_PX, available - CHAT_MIN_PX)
      : READER_MAX_PX;
  return Math.round(
    Math.max(READER_MIN_PX, Math.min(px, Math.max(READER_MIN_PX, ceiling))),
  );
}

/** Parse a persisted width, or null when there is nothing usable stored. */
export function parseStoredWidth(raw: string | null): number | null {
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

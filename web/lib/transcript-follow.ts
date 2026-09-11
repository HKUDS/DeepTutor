/**
 * Where to scroll a transcript list so the active caption row stays readable.
 *
 * Following captions is not the same as centring them. A row already
 * comfortably in view must not be nudged on every cue, or the list creeps
 * continuously while the reader is trying to read it. So the row is given a
 * band — the middle half of the viewport — and the list moves only when the
 * row would leave that band, and then only as far as the nearest edge of it.
 *
 * Kept as a pure function because the arithmetic is the whole behaviour: the
 * first attempt at this subtracted the band from the centring offset
 * unconditionally, which pushed the active row three quarters of a viewport
 * below where it belonged (off screen, or pinned to the top for early cues).
 */
export function transcriptFollowScrollTop(metrics: {
  /** The row's offset from the top of the list's scrollable content. */
  rowOffset: number;
  rowHeight: number;
  /** The list's visible height (``clientHeight``). */
  viewportHeight: number;
  /** The full scrollable height (``scrollHeight``). */
  contentHeight: number;
  currentScrollTop: number;
}): number {
  const { rowOffset, rowHeight, viewportHeight, contentHeight, currentScrollTop } = metrics;
  // The scrollTop that puts the row's centre at the viewport's centre.
  const centred = rowOffset - viewportHeight / 2 + rowHeight / 2;
  // A larger scrollTop moves the row *up*, so these two positions are where
  // the row sits at 75% and 25% of the viewport respectively.
  const band = viewportHeight * 0.25;
  const nearest = Math.min(Math.max(currentScrollTop, centred - band), centred + band);
  const maxScrollTop = Math.max(0, contentHeight - viewportHeight);
  return Math.min(Math.max(0, nearest), maxScrollTop);
}

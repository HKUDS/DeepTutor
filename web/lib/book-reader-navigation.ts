export type SequentialReadDirection = "previous" | "next";
export type ChapterScrollPlacement = "start" | "end";

/** Sub-pixel layout differences must not look like an unread page. */
export const SCROLL_EDGE_TOLERANCE_PX = 2;

interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

/**
 * Return the next in-chapter reading position, or null at that edge.
 *
 * A screenful minus a little overlap keeps lines from being split exactly at
 * the viewport boundary. The function is pure so browser behavior can be tested
 * without constructing React or DOM fixtures.
 */
export function sequentialReadTarget(
  metrics: ScrollMetrics,
  direction: SequentialReadDirection,
): number | null {
  // A detached or hidden reader can report a zero-height client box. It has
  // no readable screenfuls, so let the caller keep its current position.
  if (metrics.clientHeight <= SCROLL_EDGE_TOLERANCE_PX) return null;
  const maxScrollTop = Math.max(0, metrics.scrollHeight - metrics.clientHeight);
  if (maxScrollTop <= SCROLL_EDGE_TOLERANCE_PX) return null;

  const step = Math.max(
    metrics.clientHeight * 0.9,
    SCROLL_EDGE_TOLERANCE_PX + 1,
  );
  if (direction === "next") {
    const remaining = maxScrollTop - metrics.scrollTop;
    if (remaining <= SCROLL_EDGE_TOLERANCE_PX) return null;
    return Math.min(metrics.scrollTop + step, maxScrollTop);
  }

  if (metrics.scrollTop <= SCROLL_EDGE_TOLERANCE_PX) return null;
  return Math.max(metrics.scrollTop - step, 0);
}

export function chapterReadingPercent(metrics: ScrollMetrics): number {
  const maxScrollTop = Math.max(0, metrics.scrollHeight - metrics.clientHeight);
  if (maxScrollTop <= SCROLL_EDGE_TOLERANCE_PX) return 0;
  const percent = Math.round((metrics.scrollTop / maxScrollTop) * 100);
  return Math.min(100, Math.max(0, percent));
}

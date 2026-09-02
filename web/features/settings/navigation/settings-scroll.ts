const SETTINGS_SCROLL_SELECTOR = "[data-settings-scroll]";

export const SETTINGS_ANCHOR_EVENT = "deeptutor:settings-anchor";

export type SettingsAnchorEvent = CustomEvent<{ key: string }>;

/** Notify the resident settings document that a same-page anchor was chosen. */
export function requestSettingsSection(key: string): void {
  window.dispatchEvent(
    new CustomEvent(SETTINGS_ANCHOR_EVENT, { detail: { key } }),
  );
}

/**
 * Scroll a settings anchor inside the settings document only.
 *
 * Element.scrollIntoView() walks every scrollable ancestor, including the
 * browser viewport.  In the full-height app shell that can nudge the entire UI
 * upward even though only the settings document is meant to move.
 */
export function scrollToSettingsSection(
  key: string,
  behavior: ScrollBehavior = "smooth",
): boolean {
  const target = document.getElementById(key);
  const scroller = target?.closest<HTMLElement>(SETTINGS_SCROLL_SELECTOR);
  if (!target || !scroller) return false;

  const targetRect = target.getBoundingClientRect();
  const scrollerRect = scroller.getBoundingClientRect();
  const scrollMargin = Number.parseFloat(
    window.getComputedStyle(target).scrollMarginTop,
  );
  const top =
    scroller.scrollTop +
    targetRect.top -
    scrollerRect.top -
    (Number.isFinite(scrollMargin) ? scrollMargin : 0);

  scroller.scrollTo({ top: Math.max(0, top), behavior });

  // Fragment navigation may have moved the root scrolling element before the
  // client handler ran. Keep the full-height application shell pinned.
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  return true;
}

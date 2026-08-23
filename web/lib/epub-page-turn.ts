export type EpubPageTurnDirection = "previous" | "next";

export const EPUB_PAGE_TURN_MIN_DRAG_PX = 48;
export const EPUB_PAGE_TURN_HORIZONTAL_RATIO = 1.25;

const INTERACTIVE_SELECTOR = [
  "a",
  "button",
  "input",
  "textarea",
  "select",
  "video",
  "iframe",
  "svg",
  "pre",
  "[contenteditable='true']",
  "[data-reader-no-page-turn]",
].join(",");

export function allowsEpubPageTurn(target: EventTarget | null): boolean {
  const element = target as Element | null;
  if (!element || typeof element.closest !== "function") return false;
  return !element.closest(INTERACTIVE_SELECTOR);
}

export function resolveEpubPageTurnSwipe(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
): EpubPageTurnDirection | null {
  const dx = endX - startX;
  const dy = endY - startY;
  if (Math.abs(dx) < EPUB_PAGE_TURN_MIN_DRAG_PX) return null;
  if (Math.abs(dx) <= Math.abs(dy) * EPUB_PAGE_TURN_HORIZONTAL_RATIO)
    return null;
  return dx < 0 ? "next" : "previous";
}

export function directionForEpubLayout(
  direction: EpubPageTurnDirection,
  isRtl: boolean,
): EpubPageTurnDirection {
  if (!isRtl) return direction;
  return direction === "next" ? "previous" : "next";
}

export function hrefKey(href: string): string {
  const withoutFragment = (href || "").split("#", 1)[0];
  try {
    return decodeURIComponent(withoutFragment).replace(/^\.\//, "");
  } catch {
    return withoutFragment.replace(/^\.\//, "");
  }
}

export function locatorForEpubHref(
  href: string,
  refs: Array<{ locator: number; source_href: string }>,
): number {
  const wanted = hrefKey(href);
  const exact = refs.find((ref) => hrefKey(ref.source_href) === wanted);
  if (exact) return exact.locator;
  const suffix = refs.find(
    (ref) =>
      hrefKey(ref.source_href).endsWith(`/${wanted}`) ||
      wanted.endsWith(`/${hrefKey(ref.source_href)}`),
  );
  return suffix?.locator ?? 0;
}

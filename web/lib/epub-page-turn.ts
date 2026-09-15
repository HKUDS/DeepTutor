export type EpubPageTurnDirection = "previous" | "next";
export type EpubSpreadMode = "single" | "double";

export const EPUB_PAGE_TURN_MIN_DRAG_PX = 48;
export const EPUB_PAGE_TURN_ACTIVATION_PX = 10;
export const EPUB_PAGE_TURN_HORIZONTAL_RATIO = 1.2;
export const EPUB_PAGE_TURN_COMMIT_PROGRESS = 0.28;
export const EPUB_PAGE_TURN_FLING_VELOCITY_PX_MS = 0.55;
export const EPUB_PAGE_TURN_FLING_DISTANCE_PX = 18;
export const EPUB_PAGE_TURN_EDGE_RATIO = 0.18;
export const EPUB_PAGE_TURN_EDGE_MIN_PX = 56;
export const EPUB_PAGE_TURN_EDGE_MAX_PX = 144;
export const EPUB_SPREAD_MIN_WIDTH_PX = 900;
export const EPUB_MIN_LEAF_WIDTH_PX = 360;

export interface EpubPageTurnBounds {
  atStart: boolean;
  atEnd: boolean;
}

export function epubSpreadModeForWidth(width: number): EpubSpreadMode {
  return width >= EPUB_SPREAD_MIN_WIDTH_PX &&
    width / 2 >= EPUB_MIN_LEAF_WIDTH_PX
    ? "double"
    : "single";
}

export function canStartEpubPageTurn(
  direction: EpubPageTurnDirection,
  turning: boolean,
  bounds: EpubPageTurnBounds,
): boolean {
  if (turning) return false;
  return direction === "previous" ? !bounds.atStart : !bounds.atEnd;
}

const INTERACTIVE_SELECTOR = [
  "a",
  "button",
  "input",
  "textarea",
  "select",
  "video",
  "audio",
  "iframe",
  "pre",
  "[role='button']",
  "[onclick]",
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

export function isEpubPageTurnGesture(dx: number, dy: number): boolean {
  return (
    Math.abs(dx) >= EPUB_PAGE_TURN_ACTIVATION_PX &&
    Math.abs(dx) > Math.abs(dy) * EPUB_PAGE_TURN_HORIZONTAL_RATIO
  );
}

export function epubPageTurnDirectionForDelta(
  dx: number,
  isRtl: boolean,
): EpubPageTurnDirection | null {
  if (dx === 0) return null;
  const ltrDirection = dx < 0 ? "next" : "previous";
  return isRtl ? directionForEpubLayout(ltrDirection, true) : ltrDirection;
}

export function epubPageTurnProgress(dx: number, pageWidth: number): number {
  if (!Number.isFinite(dx) || !Number.isFinite(pageWidth) || pageWidth <= 0)
    return 0;
  return Math.min(1, Math.max(0, Math.abs(dx) / pageWidth));
}

export function shouldCommitEpubPageTurn({
  progress,
  velocityX,
  distanceX,
}: {
  progress: number;
  velocityX: number;
  distanceX: number;
}): boolean {
  return (
    progress >= EPUB_PAGE_TURN_COMMIT_PROGRESS ||
    (Math.abs(distanceX) >= EPUB_PAGE_TURN_FLING_DISTANCE_PX &&
      Math.abs(velocityX) >= EPUB_PAGE_TURN_FLING_VELOCITY_PX_MS &&
      Math.sign(velocityX) === Math.sign(distanceX))
  );
}

export function resolveEpubPageTurnRelease({
  cancelled,
  hasSelection,
  directionMatches,
  reducedMotion,
  progress,
  velocityX,
  distanceX,
}: {
  cancelled: boolean;
  hasSelection: boolean;
  directionMatches: boolean;
  reducedMotion: boolean;
  progress: number;
  velocityX: number;
  distanceX: number;
}): "commit" | "settle" | "idle" {
  const commits =
    !cancelled &&
    !hasSelection &&
    directionMatches &&
    shouldCommitEpubPageTurn({ progress, velocityX, distanceX });
  if (commits) return "commit";
  return reducedMotion ? "idle" : "settle";
}

export function epubPageTurnSettleDuration(progress: number): number {
  const bounded = Math.min(1, Math.max(0, progress));
  return Math.round(220 - bounded * 80);
}

export function epubEdgeTapDirection(
  x: number,
  width: number,
  isRtl: boolean,
): EpubPageTurnDirection | null {
  if (!Number.isFinite(x) || !Number.isFinite(width) || width <= 0) return null;
  const edgeWidth = Math.min(
    EPUB_PAGE_TURN_EDGE_MAX_PX,
    Math.max(EPUB_PAGE_TURN_EDGE_MIN_PX, width * EPUB_PAGE_TURN_EDGE_RATIO),
  );
  if (x <= edgeWidth) return isRtl ? "next" : "previous";
  if (x >= width - edgeWidth) return isRtl ? "previous" : "next";
  return null;
}

export function bufferEpubPageTurn(
  active: EpubPageTurnDirection,
  buffered: EpubPageTurnDirection | null,
  requested: EpubPageTurnDirection,
): EpubPageTurnDirection | null {
  if (buffered) return buffered;
  return requested === active ? requested : null;
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

export type BilingualReaderMode = "inline" | "dual" | "hover";
export type BilingualTheme = "system" | "sepia" | "dark" | "oled";
export type BilingualFontSize = "sm" | "base" | "lg" | "xl" | "2xl";
export type BilingualFontFamily = "sans" | "serif";

export const BILINGUAL_READER_MODE_STORAGE_KEY = "deeptutor.bilingual-reader.mode";
export const BILINGUAL_DUAL_PANE_MIN_CONTAINER_WIDTH_PX = 960;
export const BILINGUAL_DUAL_SCROLL_MANUAL_DRAG_PX = 8;
export const BILINGUAL_CLICK_LOOKUP_STORAGE_KEY = "deeptutor.bilingual-reader.click-lookup";
export const BILINGUAL_THEME_STORAGE_KEY = "deeptutor.bilingual-reader.theme";
export const BILINGUAL_FONT_SIZE_STORAGE_KEY = "deeptutor.bilingual-reader.font-size";
export const BILINGUAL_FONT_FAMILY_STORAGE_KEY = "deeptutor.bilingual-reader.font-family";

export function parseBilingualReaderMode(value: string | null): BilingualReaderMode {
  return value === "dual" || value === "hover" ? value : "inline";
}

export function parseBilingualTheme(value: string | null): BilingualTheme {
  return value === "sepia" || value === "dark" || value === "oled" ? value : "system";
}

export function parseBilingualFontSize(value: string | null): BilingualFontSize {
  return value === "sm" || value === "lg" || value === "xl" || value === "2xl" ? value : "base";
}

export function parseBilingualFontFamily(value: string | null): BilingualFontFamily {
  return value === "serif" ? "serif" : "sans";
}

export function parseStoredBoolean(value: string | null): boolean {
  return value === "true";
}

export function supportsDualPaneAtContainerWidth(width: number | null | undefined): boolean {
  return typeof width === "number" && Number.isFinite(width) && width >= BILINGUAL_DUAL_PANE_MIN_CONTAINER_WIDTH_PX;
}

export function breaksDualScrollLink(input: {
  type?: string;
  dx?: number;
  dy?: number;
}): boolean {
  if (input.type === "wheel") return true;
  const dx = input.dx || 0;
  const dy = input.dy || 0;
  return Math.sqrt(dx * dx + dy * dy) >= BILINGUAL_DUAL_SCROLL_MANUAL_DRAG_PX;
}

export function visibleGroupFromElements(
  elements: HTMLElement[],
  scrollTop: number,
  viewportHeight: number,
  fallback = 0,
): number {
  let visible = fallback;
  for (const element of elements) {
    if (element.offsetTop + element.offsetHeight >= scrollTop + Math.min(24, viewportHeight / 8)) {
      visible = Number(element.dataset.groupIndex || 0);
      break;
    }
  }
  return visible;
}

export function scrollPaneToGroup(
  pane: HTMLElement | null,
  groupIndex: number,
  behavior: ScrollBehavior = "auto",
  offsetTopOffset = 48,
): boolean {
  const group = pane?.querySelector<HTMLElement>(`[data-group-index="${groupIndex}"]`);
  if (!pane || !group) return false;
  const targetTop = Math.max(0, group.offsetTop - offsetTopOffset);
  pane.scrollTo({ top: targetTop, behavior });
  return true;
}

export function shouldIgnoreLookupTarget(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    !!target.closest("button, a, input, textarea, select, summary, details, [data-reader-control]")
  );
}

export function isParagraphSideTap(
  point: { x: number; y: number },
  line: { left: number; right: number; top: number; bottom: number },
  gap = 4,
): boolean {
  const inLine = point.y >= line.top - 4 && point.y <= line.bottom + 4;
  return inLine && point.x >= line.right + gap;
}

export type ParagraphSwipeDirection = "previous" | "next";

export function paragraphSwipeFromPoints(
  start: { x: number; y: number },
  end: { x: number; y: number },
  viewportWidth: number,
  options: { edgeInset?: number; minDistance?: number; maxVertical?: number } = {},
): ParagraphSwipeDirection | null {
  const edgeInset = options.edgeInset ?? 46;
  const minDistance = options.minDistance ?? 52;
  const maxVertical = options.maxVertical ?? 30;
  if (start.x <= edgeInset || start.x >= viewportWidth - edgeInset) return null;

  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (Math.abs(dx) < minDistance || Math.abs(dy) > maxVertical) return null;
  if (Math.abs(dy) > Math.abs(dx)) return null;
  return dx < 0 ? "next" : "previous";
}

export function nextReaderToolbarVisible(
  current: boolean,
  scrollDelta: number,
  threshold = 6,
): boolean {
  if (scrollDelta <= -threshold) return true;
  if (scrollDelta >= threshold) return false;
  return current;
}

export type BilingualReaderShortcut =
  | "previous-group"
  | "next-group"
  | "toggle-translation"
  | "lookup"
  | "bookmark"
  | "pronounce"
  | "pronounce-uk"
  | "toggle-shortcuts"
  | "close-modal";

export function readerShortcutFromKeyboardEvent(
  event: KeyboardEvent,
  options: { modalOpen?: boolean } = {},
): BilingualReaderShortcut | null {
  if (event.metaKey || event.ctrlKey || event.altKey) return null;
  const target = event.target;
  if (
    typeof HTMLElement !== "undefined" &&
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  ) {
    return null;
  }

  // Handle escape when modals/panels are open
  if (event.key === "Escape") {
    return "close-modal";
  }

  if (options.modalOpen) {
    return null;
  }

  // Shift + P for explicit UK pronunciation
  if (event.shiftKey && (event.key === "P" || event.key === "p")) {
    return "pronounce-uk";
  }

  // Shift + ? for keyboard shortcuts help
  if (event.key === "?" || (event.shiftKey && event.key === "/")) {
    return "toggle-shortcuts";
  }

  switch (event.key.toLowerCase()) {
    case "j":
    case "arrowdown":
      return "next-group";
    case "k":
    case "arrowup":
      return "previous-group";
    case "t":
      return "toggle-translation";
    case "d":
      return "lookup";
    case "b":
      return "bookmark";
    case "p":
      return "pronounce";
    case "h":
      return "toggle-shortcuts";
    default:
      return null;
  }
}

/** Resolve the word under a caret without stealing the user's current selection. */
export function wordRangeAtPoint(container: HTMLElement, x: number, y: number): Range | null {
  const caret = document.caretRangeFromPoint?.(x, y);
  if (!caret || !container.contains(caret.startContainer)) return null;

  const text = container.textContent || "";
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let cursor = 0;
  let offset = -1;
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const content = node.textContent || "";
    if (node === caret.startContainer) {
      offset = cursor + Math.min(caret.startOffset, content.length);
      break;
    }
    cursor += content.length;
  }
  if (offset < 0) return null;

  let start = offset;
  let end = offset;
  while (start > 0 && /[\p{L}\p{N}'’_-]/u.test(text[start - 1] ?? "")) start--;
  while (end < text.length && /[\p{L}\p{N}'’_-]/u.test(text[end] ?? "")) end++;
  const word = text.slice(start, end);
  if (!/\p{L}/u.test(word)) return null;

  const range = document.createRange();
  let rangeCursor = 0;
  let rangeStart: { node: Node; offset: number } | null = null;
  let rangeEnd: { node: Node; offset: number } | null = null;
  const rangeWalker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  while ((node = rangeWalker.nextNode())) {
    const content = node.textContent || "";
    const nodeEnd = rangeCursor + content.length;
    if (!rangeStart && start >= rangeCursor && start <= nodeEnd) {
      rangeStart = { node, offset: start - rangeCursor };
    }
    if (end >= rangeCursor && end <= nodeEnd) {
      rangeEnd = { node, offset: end - rangeCursor };
      break;
    }
    rangeCursor = nodeEnd;
  }
  if (!rangeStart || !rangeEnd) return null;
  range.setStart(rangeStart.node, rangeStart.offset);
  range.setEnd(rangeEnd.node, rangeEnd.offset);
  return range;
}

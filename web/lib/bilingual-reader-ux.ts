export type BilingualReaderMode = "inline" | "dual" | "hover";
export type BilingualTheme = "system" | "sepia" | "dark" | "oled";
export type BilingualFontSize = "sm" | "base" | "lg" | "xl" | "2xl";
export type BilingualFontFamily = "sans" | "serif";

export const BILINGUAL_READER_MODE_STORAGE_KEY = "deeptutor.bilingual-reader.mode";
export const BILINGUAL_DUAL_PANE_MEDIA_QUERY = "(min-width: 1180px)";
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

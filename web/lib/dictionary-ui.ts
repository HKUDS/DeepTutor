export interface DictionaryAnchorRect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface DictionaryPopoverPosition {
  left: number;
  top: number;
  placement: "above" | "below";
}

const WORD_RE = /[A-Za-z]+(?:['’\-][A-Za-z]+)*/g;

/** Return one English token suitable for a dictionary lookup. */
export function extractDictionaryWord(selectedText: string): string {
  const words = selectedText.trim().match(WORD_RE) ?? [];
  return words.length === 1 ? words[0] : "";
}

/**
 * Keep a fixed-position dictionary popover inside the viewport. The caller
 * supplies the measured popover size, so long definitions are positioned from
 * the actual rendered height rather than a guessed constant.
 */
export function positionDictionaryPopover(
  anchor: DictionaryAnchorRect,
  size: { width: number; height: number },
  viewport: { width: number; height: number },
  gap = 8,
): DictionaryPopoverPosition {
  const margin = 8;
  const anchorX = (anchor.left + anchor.right) / 2;
  const aboveTop = anchor.top - size.height - gap;
  const belowTop = anchor.bottom + gap;
  const canPlaceAbove = aboveTop >= margin;
  const canPlaceBelow = belowTop + size.height <= viewport.height - margin;
  const placement = canPlaceAbove || !canPlaceBelow ? "above" : "below";
  const preferredTop = placement === "above" ? aboveTop : belowTop;
  const top = Math.max(margin, Math.min(preferredTop, viewport.height - size.height - margin));
  const left = Math.max(
    margin,
    Math.min(anchorX - size.width / 2, viewport.width - size.width - margin),
  );
  return { left, top, placement };
}

export function nextDictionarySheetExpanded(
  current: boolean,
  dragDeltaY: number,
  viewportHeight: number,
): boolean {
  const threshold = Math.max(36, Math.round(viewportHeight * 0.08));
  if (dragDeltaY <= -threshold) return true;
  if (dragDeltaY >= threshold) return false;
  return current;
}

export function chineseRevealClassName(revealed: boolean): string {
  const base =
    "mt-0.5 block w-fit rounded text-left text-sm font-normal leading-relaxed " +
    "text-[var(--muted-foreground)] transition focus-visible:outline " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary)]";
  return revealed
    ? `${base} cursor-default`
    : `${base} cursor-pointer select-none blur-[5px] underline decoration-dashed underline-offset-2 active:blur-[2px]`;
}

/**
 * Placement for a menu that hangs off a row inside a narrow, scrolling panel.
 *
 * The sidebar is ~220px wide and its lists scroll, so a menu anchored to a row
 * has to escape the panel horizontally and flip vertically near the bottom of
 * the window. Callers render it in a portal at these fixed coordinates.
 */

export interface FloatingMenuPosition {
  left: number;
  top: number;
  maxHeight: number;
  openUpward: boolean;
}

const MENU_GAP = 8;
const VIEWPORT_MARGIN = 12;
const MAX_MENU_HEIGHT = 380;

export function placeMenu(
  anchor: DOMRect,
  menuWidth: number,
): FloatingMenuPosition {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const preferredHeight = Math.min(
    MAX_MENU_HEIGHT,
    viewportHeight - VIEWPORT_MARGIN * 2,
  );
  const roomBelow = viewportHeight - anchor.bottom - MENU_GAP - VIEWPORT_MARGIN;
  const roomAbove = anchor.top - MENU_GAP - VIEWPORT_MARGIN;
  const openUpward = roomBelow < preferredHeight && roomAbove > roomBelow;
  const maxHeight = Math.max(
    140,
    Math.min(preferredHeight, openUpward ? roomAbove : roomBelow),
  );

  const roomRight = viewportWidth - anchor.right - MENU_GAP - VIEWPORT_MARGIN;
  const roomLeft = anchor.left - MENU_GAP - VIEWPORT_MARGIN;
  const preferredLeft =
    roomRight >= menuWidth || roomRight >= roomLeft
      ? anchor.right + MENU_GAP
      : anchor.left - menuWidth - MENU_GAP;
  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(preferredLeft, viewportWidth - menuWidth - VIEWPORT_MARGIN),
  );
  const top = openUpward ? anchor.top - MENU_GAP : anchor.bottom + MENU_GAP;

  return { left, top, maxHeight, openUpward };
}

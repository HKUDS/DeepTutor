export type TooltipSide = "top" | "right" | "bottom" | "left";

export interface TooltipPosition {
  left: number;
  top: number;
  side: TooltipSide;
}

const GAP = 8;
const VIEWPORT_MARGIN = 8;

function opposite(side: TooltipSide): TooltipSide {
  if (side === "top") return "bottom";
  if (side === "bottom") return "top";
  if (side === "left") return "right";
  return "left";
}

function coordinates(
  anchor: DOMRect,
  tooltip: DOMRect,
  side: TooltipSide,
): { left: number; top: number } {
  if (side === "top") {
    return {
      left: anchor.left + (anchor.width - tooltip.width) / 2,
      top: anchor.top - tooltip.height - GAP,
    };
  }
  if (side === "bottom") {
    return {
      left: anchor.left + (anchor.width - tooltip.width) / 2,
      top: anchor.bottom + GAP,
    };
  }
  if (side === "left") {
    return {
      left: anchor.left - tooltip.width - GAP,
      top: anchor.top + (anchor.height - tooltip.height) / 2,
    };
  }
  return {
    left: anchor.right + GAP,
    top: anchor.top + (anchor.height - tooltip.height) / 2,
  };
}

export function placeTooltip(
  anchor: DOMRect,
  tooltip: DOMRect,
  preferred: TooltipSide,
  viewportWidth: number,
  viewportHeight: number,
): TooltipPosition {
  let side = preferred;
  let point = coordinates(anchor, tooltip, side);
  const overflowsPreferred =
    (side === "top" && point.top < VIEWPORT_MARGIN) ||
    (side === "bottom" && point.top + tooltip.height > viewportHeight - VIEWPORT_MARGIN) ||
    (side === "left" && point.left < VIEWPORT_MARGIN) ||
    (side === "right" && point.left + tooltip.width > viewportWidth - VIEWPORT_MARGIN);
  if (overflowsPreferred) {
    const flipped = opposite(side);
    const flippedPoint = coordinates(anchor, tooltip, flipped);
    const flippedFits =
      flippedPoint.left >= VIEWPORT_MARGIN &&
      flippedPoint.top >= VIEWPORT_MARGIN &&
      flippedPoint.left + tooltip.width <= viewportWidth - VIEWPORT_MARGIN &&
      flippedPoint.top + tooltip.height <= viewportHeight - VIEWPORT_MARGIN;
    if (flippedFits) {
      side = flipped;
      point = flippedPoint;
    }
  }
  return {
    side,
    left: Math.min(
      Math.max(point.left, VIEWPORT_MARGIN),
      Math.max(VIEWPORT_MARGIN, viewportWidth - tooltip.width - VIEWPORT_MARGIN),
    ),
    top: Math.min(
      Math.max(point.top, VIEWPORT_MARGIN),
      Math.max(VIEWPORT_MARGIN, viewportHeight - tooltip.height - VIEWPORT_MARGIN),
    ),
  };
}

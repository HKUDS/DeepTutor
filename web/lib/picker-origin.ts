/**
 * Tiny module-level handoff for "expand from the clicked element" picker
 * animations.
 *
 * When a menu row that opens a fullscreen picker is clicked, the trigger
 * records its on-screen rect here. `PickerShell` reads it on open and animates
 * the modal card *outward from that rect* — so the picker feels like it grows
 * out of the row the user tapped, rather than popping in at screen center.
 *
 * The value is freshness-gated rather than consumed/cleared: a `peek` is
 * idempotent (safe under React's double-render in dev) and a stale origin
 * (e.g. a picker opened from somewhere other than the menu) simply falls back
 * to the default centered animation.
 */

interface PickerOrigin {
  rect: DOMRect;
  ts: number;
}

let current: PickerOrigin | null = null;

export function setPickerOrigin(rect: DOMRect): void {
  current = { rect, ts: Date.now() };
}

/**
 * Return the last trigger rect if it was set within `maxAgeMs` (the click →
 * open hop happens in the same tick, so the window is generous). Idempotent.
 */
export function peekPickerOrigin(maxAgeMs = 700): DOMRect | null {
  if (!current) return null;
  if (Date.now() - current.ts > maxAgeMs) return null;
  return current.rect;
}

/** Map the final surface back onto the actual trigger, including off-center layouts. */
export function pickerFlight(
  source: Pick<DOMRect, "x" | "y" | "width" | "height">,
  target: Pick<DOMRect, "x" | "y" | "width" | "height">,
) {
  return {
    x: source.x + source.width / 2 - target.x - target.width / 2,
    y: source.y + source.height / 2 - target.y - target.height / 2,
    scaleX: target.width > 0 ? source.width / target.width : 1,
    scaleY: target.height > 0 ? source.height / target.height : 1,
  };
}

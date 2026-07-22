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

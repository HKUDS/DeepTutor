/**
 * Geometry for the partner roster strip.
 *
 * Items keep their natural spacing in the middle of the strip. Inside the
 * zone at an edge that still has partners beyond it, spacing tightens
 * exponentially toward a floor and each avatar shrinks with its local spacing,
 * so the gaps between them close steadily without the avatars ever touching;
 * the strip's edge fade takes the last of them. A side only compresses as far as there is content to
 * scroll back to, so a strip at its start, or a roster that fits, stays flat.
 */

export interface RosterLensInput {
  /** Item centre in content coordinates (offsetLeft + width / 2). */
  center: number
  /** Visible strip width. */
  viewport: number
  scrollLeft: number
  /** scrollWidth - clientWidth. */
  maxScroll: number
  /** How far the compression reaches into the strip from each edge. */
  zone: number
}

export interface RosterLens {
  /** Horizontal shift from the item's layout position. */
  dx: number
  scale: number
  opacity: number
  /** Name opacity; names leave before the avatars do. */
  label: number
  /** How compressed the item is, 0 (flat) to 1. */
  depth: number
}

/** Tightest spacing, as a share of the natural one. */
const MIN_SPACING = 0.3
/**
 * Avatar scale per unit of local spacing. Neighbours stay apart while
 * slot * f >= avatar * scale; for the roster's 46px slots and 32px avatars
 * that holds for any scale <= 1.43 f; 1.15 f leaves room for the step between
 * an item's own spacing and the gap to its neighbour.
 */
const SCALE_PER_SPACING = 1.15
const MIN_OPACITY = 0.4

const clamp01 = (value: number) => Math.min(1, Math.max(0, value))

/**
 * Visual distance into the zone for a layout distance `into`: the integral of
 * a spacing factor that decays as exp(-x / falloff) down to MIN_SPACING.
 */
function compressed(into: number, falloff: number): number {
  const knee = -falloff * Math.log(MIN_SPACING)
  if (into <= knee) return falloff * (1 - Math.exp(-into / falloff))
  return falloff * (1 - MIN_SPACING) + MIN_SPACING * (into - knee)
}

export function rosterLens({ center, viewport, scrollLeft, maxScroll, zone }: RosterLensInput): RosterLens {
  const flat: RosterLens = { dx: 0, scale: 1, opacity: 1, label: 1, depth: 0 }
  if (viewport <= 0 || zone <= 0) return flat
  const position = center - scrollLeft
  const intoLeft = zone - position
  const intoRight = position - (viewport - zone)
  const side = intoLeft >= intoRight ? -1 : 1
  const into = Math.max(intoLeft, intoRight)
  if (into <= 0) return flat
  // Compression is only as present as the content it stands for.
  const strength = clamp01((side < 0 ? scrollLeft : maxScroll - scrollLeft) / zone)
  if (strength === 0) return flat

  const falloff = zone * 0.9
  const target = side < 0 ? zone - compressed(into, falloff) : viewport - zone + compressed(into, falloff)
  const spacing = Math.max(MIN_SPACING, Math.exp(-into / falloff))
  const fullScale = Math.min(1, spacing * SCALE_PER_SPACING)
  const depth = (1 - spacing) / (1 - MIN_SPACING) * strength
  return {
    dx: (target - position) * strength,
    scale: 1 - (1 - fullScale) * strength,
    opacity: 1 - (1 - MIN_OPACITY) * depth,
    label: 1 - clamp01((into / (zone * 0.5)) * strength),
    depth,
  }
}

/** Edge fade per side, in px: present only where content continues. */
export function rosterFade({ viewport, scrollLeft, maxScroll, zone }: Omit<RosterLensInput, 'center'>) {
  if (viewport <= 0 || zone <= 0) return { left: 0, right: 0 }
  const reach = zone * 0.4
  return {
    left: reach * clamp01(scrollLeft / zone),
    right: reach * clamp01((maxScroll - scrollLeft) / zone),
  }
}

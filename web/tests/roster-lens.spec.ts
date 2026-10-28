import { describe, expect, it } from 'vitest'
import { rosterFade, rosterLens } from '@/components/sidebar/roster-lens'

// The roster's real geometry: 46px slots, 32px avatars, 52px zones, 8 partners.
const SLOT = 46
const AVATAR = 32
const ZONE = 52
const VIEWPORT = 255
const COUNT = 8
const MAX_SCROLL = SLOT * COUNT - VIEWPORT

function avatars(scrollLeft: number, maxScroll = MAX_SCROLL) {
  return Array.from({ length: COUNT }, (_, index) => {
    const center = index * SLOT + SLOT / 2
    const lens = rosterLens({ center, viewport: VIEWPORT, scrollLeft, maxScroll, zone: ZONE })
    const visual = center - scrollLeft + lens.dx
    const half = (AVATAR * lens.scale) / 2
    return { ...lens, left: visual - half, right: visual + half }
  })
}

describe('rosterLens', () => {
  it('leaves a roster that fits completely flat', () => {
    for (const item of avatars(0, 0)) expect(item).toMatchObject({ dx: 0, scale: 1, opacity: 1, label: 1, depth: 0 })
  })

  it('compresses only the side that has partners beyond it', () => {
    const items = avatars(0)
    expect(items[0].depth).toBe(0)
    expect(items.at(-1)!.depth).toBeGreaterThan(0.5)
    expect(items.at(-1)!.label).toBe(0)
  })

  it('packs toward an edge with ever-tighter gaps but never lets avatars touch', () => {
    for (let scrollLeft = 0; scrollLeft <= MAX_SCROLL; scrollLeft += 3) {
      const items = avatars(scrollLeft)
      const gaps = items.slice(1).map((item, index) => item.left - items[index].right)
      for (const gap of gaps) expect(gap).toBeGreaterThan(0.5)
    }
    const atStart = avatars(0)
    const gaps = atStart.slice(1).map((item, index) => item.left - atStart[index].right)
    const firstCompressed = gaps.findIndex(gap => gap < SLOT - AVATAR - 0.01)
    expect(firstCompressed).toBeGreaterThan(0)
    expect(gaps[firstCompressed + 1]).toBeLessThan(gaps[firstCompressed])
  })

  it('moves items continuously as a stack starts to form', () => {
    const still = avatars(0)
    const nudged = avatars(0.5)
    still.forEach((item, index) => expect(Math.abs(nudged[index].left + 0.5 - item.left)).toBeLessThan(1.5))
  })
})

describe('rosterFade', () => {
  it('fades only edges with content past them', () => {
    expect(rosterFade({ viewport: VIEWPORT, scrollLeft: 0, maxScroll: MAX_SCROLL, zone: ZONE })).toMatchObject({ left: 0 })
    expect(rosterFade({ viewport: VIEWPORT, scrollLeft: MAX_SCROLL, maxScroll: MAX_SCROLL, zone: ZONE }).right).toBe(0)
    expect(rosterFade({ viewport: VIEWPORT, scrollLeft: 0, maxScroll: 0, zone: ZONE })).toEqual({ left: 0, right: 0 })
  })
})

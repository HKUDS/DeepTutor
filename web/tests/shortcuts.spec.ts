import { describe, expect, it } from 'vitest'
import { SHORTCUTS, matchesShortcut, shortcutKeys } from '@/lib/shortcuts'

const key = (init: KeyboardEventInit) => new KeyboardEvent('keydown', init)

describe('shortcuts', () => {
  it('matches ⌥-digit by physical key, since macOS rewrites event.key', () => {
    const optionTwo = key({ key: '™', code: 'Digit2', metaKey: true, altKey: true })
    expect(matchesShortcut(optionTwo, SHORTCUTS.category(1), true)).toBe(true)
    expect(matchesShortcut(optionTwo, SHORTCUTS.category(0), true)).toBe(false)
  })

  it('uses ⌘ on macOS and Ctrl elsewhere, and requires the exact modifiers', () => {
    expect(matchesShortcut(key({ key: 'k', code: 'KeyK', metaKey: true }), SHORTCUTS.search, true)).toBe(true)
    expect(matchesShortcut(key({ key: 'k', code: 'KeyK', ctrlKey: true }), SHORTCUTS.search, true)).toBe(false)
    expect(matchesShortcut(key({ key: 'k', code: 'KeyK', ctrlKey: true }), SHORTCUTS.search, false)).toBe(true)
    expect(matchesShortcut(key({ key: 'K', code: 'KeyK', metaKey: true, shiftKey: true }), SHORTCUTS.search, true)).toBe(false)
  })

  it('prints the same keys it matches', () => {
    expect(shortcutKeys(SHORTCUTS.newChat, true)).toEqual(['⌘', '⇧', 'O'])
    expect(shortcutKeys(SHORTCUTS.category(2), false)).toEqual(['Ctrl', 'Alt', '3'])
  })
})

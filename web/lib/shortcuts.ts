/**
 * Keyboard shortcuts: one description used both to match a key event and to
 * print the keys in a tooltip, so the two can never disagree.
 */

export interface Shortcut {
  /** A letter or digit, e.g. "K" or "1". */
  key: string
  /** ⌘ on macOS, Ctrl elsewhere. */
  mod?: boolean
  alt?: boolean
  shift?: boolean
}

export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  return /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent)
}

/** The keys as printed: ⌘ ⌥ ⇧ K on macOS, Ctrl Alt Shift K elsewhere. */
export function shortcutKeys(shortcut: Shortcut, mac = isMacPlatform()): string[] {
  const keys: string[] = []
  if (shortcut.mod) keys.push(mac ? '⌘' : 'Ctrl')
  if (shortcut.alt) keys.push(mac ? '⌥' : 'Alt')
  if (shortcut.shift) keys.push(mac ? '⇧' : 'Shift')
  keys.push(shortcut.key.toUpperCase())
  return keys
}

function physicalCode(key: string): string {
  return /^\d$/.test(key) ? `Digit${key}` : `Key${key.toUpperCase()}`
}

export function matchesShortcut(event: KeyboardEvent, shortcut: Shortcut, mac = isMacPlatform()): boolean {
  const mod = mac ? event.metaKey : event.ctrlKey
  if (Boolean(shortcut.mod) !== mod) return false
  if (Boolean(shortcut.alt) !== event.altKey || Boolean(shortcut.shift) !== event.shiftKey) return false
  // ⌥ rewrites event.key on macOS (⌥1 is "¡"), so compare the physical key.
  return event.code === physicalCode(shortcut.key)
}

/** The modern shell's shortcuts, in one place. */
export const SHORTCUTS = {
  search: { key: 'K', mod: true },
  newChat: { key: 'O', mod: true, shift: true },
  /** A side chat with Dito about the open conversation, in the viewer. */
  sideChat: { key: 'S', mod: true, alt: true },
  category: (index: number): Shortcut => ({ key: String(index + 1), mod: true, alt: true }),
} as const

/** Same policy as the persisted note schema; never render executable URLs. */
export function safeNoteUrl(value: unknown): string | null {
  return typeof value === 'string' && /^(https?:\/\/|mailto:|\/(?!\/)|#)/i.test(value.trim())
    ? value.trim()
    : null
}

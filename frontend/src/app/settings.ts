import { apiFetch } from '../api/http'

export type ThemeId = 'light' | 'dark'
export type LanguageId = 'zh' | 'en'
export type LocalLinkOpenMode = 'ask' | 'builtin' | 'system'

export type VoiceShortcut = {
  enabled: boolean
  ctrl: boolean
  alt: boolean
  shift: boolean
  meta: boolean
  key: string
}

export type GeneralSettings = {
  voiceShortcut: VoiceShortcut
  localLinkOpen: LocalLinkOpenMode
  artifactPath: string
}

export const LS_LANGUAGE = 'trae:language'
export const LS_GENERAL = 'deeptutor:general-settings'

export const DEFAULT_VOICE_SHORTCUT: VoiceShortcut = {
  enabled: true,
  ctrl: true,
  alt: false,
  shift: false,
  meta: false,
  key: 'v',
}

export const DEFAULT_GENERAL: GeneralSettings = {
  voiceShortcut: DEFAULT_VOICE_SHORTCUT,
  localLinkOpen: 'ask',
  artifactPath: '~/Library/Application Support/DeepTutor',
}

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function loadGeneralSettings(): GeneralSettings {
  const saved = readJson<Partial<GeneralSettings>>(LS_GENERAL)
  if (!saved) return { ...DEFAULT_GENERAL, voiceShortcut: { ...DEFAULT_VOICE_SHORTCUT } }
  return {
    voiceShortcut: { ...DEFAULT_VOICE_SHORTCUT, ...(saved.voiceShortcut || {}) },
    localLinkOpen: saved.localLinkOpen === 'builtin' || saved.localLinkOpen === 'system'
      ? saved.localLinkOpen
      : 'ask',
    artifactPath: typeof saved.artifactPath === 'string' && saved.artifactPath.trim()
      ? saved.artifactPath
      : DEFAULT_GENERAL.artifactPath,
  }
}

export function saveGeneralSettings(next: GeneralSettings): void {
  try {
    localStorage.setItem(LS_GENERAL, JSON.stringify(next))
  } catch { /* ignore storage errors */ }
}

export function persistInterfaceSettings(patch: { theme?: ThemeId; language?: LanguageId }): void {
  apiFetch('/api/v1/settings/ui', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }).catch(() => { /* backend optional for the shell */ })
}

export function formatShortcut(shortcut: VoiceShortcut): string[] {
  const keys: string[] = []
  if (shortcut.ctrl) keys.push('⌃')
  if (shortcut.alt) keys.push('⌥')
  if (shortcut.shift) keys.push('⇧')
  if (shortcut.meta) keys.push('⌘')
  keys.push((shortcut.key || '').toUpperCase() || '…')
  return keys
}

export function shortcutFromKeyboardEvent(e: KeyboardEvent): VoiceShortcut | null {
  if (e.key === 'Escape' || e.key === 'Tab') return null
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
  if (key === 'control' || key === 'shift' || key === 'alt' || key === 'meta') return null
  return {
    enabled: true,
    ctrl: e.ctrlKey,
    alt: e.altKey,
    shift: e.shiftKey,
    meta: e.metaKey,
    key,
  }
}

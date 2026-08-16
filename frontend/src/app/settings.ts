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
export const LS_RESPONSE_LANGUAGE = 'deeptutor:response-language'
export const LS_VOICE_AUTOPLAY = 'deeptutor:voice-autoplay'
export const LS_CHAT_TIMEOUT = 'deeptutor:chat-timeout'
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

export const DEFAULT_CHAT_TIMEOUT = 180
export const CHAT_TIMEOUT_MIN = 30
export const CHAT_TIMEOUT_MAX = 1800
export const CHAT_TIMEOUT_OPTIONS = [30, 60, 180, 300, 600, 1800] as const

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

export function persistInterfaceSettings(patch: {
  theme?: ThemeId
  language?: LanguageId
  response_language?: LanguageId
}): void {
  apiFetch('/api/v1/settings/ui', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }).catch(() => { /* backend optional for the shell */ })
}

export function persistVoiceAutoplay(voiceAutoplay: boolean): void {
  try { localStorage.setItem(LS_VOICE_AUTOPLAY, voiceAutoplay ? '1' : '0') } catch { /* ignore */ }
  apiFetch('/api/v1/settings/voice-autoplay', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voice_autoplay: voiceAutoplay }),
  }).catch(() => { /* backend optional for the shell */ })
}

export function persistChatTimeout(seconds: number): void {
  const value = clampChatTimeout(seconds)
  try { localStorage.setItem(LS_CHAT_TIMEOUT, String(value)) } catch { /* ignore */ }
  apiFetch('/api/v1/settings/chat-response-timeout', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_response_timeout: value }),
  }).catch(() => { /* backend optional for the shell */ })
}

export type RuntimeUiSettings = {
  theme?: string
  language?: LanguageId
  response_language?: LanguageId
  voice_autoplay?: boolean
  chat_response_timeout?: number
}

export async function loadRuntimeUiSettings(): Promise<RuntimeUiSettings> {
  try {
    const response = await apiFetch('/api/v1/settings')
    if (response.ok) {
      const payload = await response.json() as { ui?: RuntimeUiSettings }
      if (payload.ui && typeof payload.ui === 'object') return payload.ui
    }
  } catch { /* fall through */ }
  try {
    const response = await apiFetch('/api/v1/settings/ui')
    if (response.ok) return await response.json() as RuntimeUiSettings
  } catch { /* ignore */ }
  return {}
}

export function clampChatTimeout(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_CHAT_TIMEOUT
  return Math.min(CHAT_TIMEOUT_MAX, Math.max(CHAT_TIMEOUT_MIN, Math.round(value)))
}

export function formatTimeoutLabel(seconds: number, language: LanguageId): string {
  if (seconds < 60) return language === 'zh' ? `${seconds} 秒` : `${seconds} sec`
  const minutes = seconds / 60
  if (Number.isInteger(minutes)) {
    return language === 'zh' ? `${minutes} 分钟` : (minutes === 1 ? '1 min' : `${minutes} min`)
  }
  return language === 'zh' ? `${seconds} 秒` : `${seconds} sec`
}

export function timeoutSelectOptions(current: number, language: LanguageId): { value: string; label: string }[] {
  const values = new Set<number>(CHAT_TIMEOUT_OPTIONS)
  values.add(clampChatTimeout(current))
  return [...values]
    .sort((a, b) => a - b)
    .map((seconds) => ({ value: String(seconds), label: formatTimeoutLabel(seconds, language) }))
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

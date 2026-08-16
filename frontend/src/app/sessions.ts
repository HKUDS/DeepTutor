import { getSession, listSessions, type SessionMessage, type SessionSummary } from '../api/sessions'
import type { StreamEvent } from '../api/ws'
import { ChatMessage, MessageBlock, initialMessages, taskList } from '../mock/data'
import { PRODUCT_NAME } from './brand'

export const NEW_SESSION_TITLE = '新对话'
export const STREAM_CONNECT_ERROR = `无法连接 ${PRODUCT_NAME} 后端，请确认本地 API 已启动。`
export const STREAM_FAIL_ERROR = '回复失败，请重试。'
export const CREATE_SESSION_ERROR = '会话创建失败，请重试。'

const LS_SESSIONS = 'deeptutor:sessions'
const LS_SELECTED = 'deeptutor:selectedSession'

export const CAPABILITIES = [
  { id: 'chat', label: '对话' },
  { id: 'deep_solve', label: '深度求解' },
  { id: 'deep_question', label: '出题' },
  { id: 'deep_research', label: '深度研究' },
  { id: 'visualize', label: '可视化' },
  { id: 'mastery_path', label: '引导学习' },
] as const

export type CapabilityId = (typeof CAPABILITIES)[number]['id']

export type FileAttachment = {
  type: string
  filename: string
  mime_type?: string
  base64?: string
}

export type ChassisSession = {
  id: string
  backendId: string | null
  label: string
  time: string
  messages: ChatMessage[]
  status?: string
  pinned?: boolean
}

export function formatClock(date = new Date()): string {
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

export function formatEpoch(value: number): string {
  if (!value) return ''
  const ms = value < 1e12 ? value * 1000 : value
  return formatClock(new Date(ms))
}

/** TraeWork: first paint uses the new-action stub, then a short title from the first user line. */
export function deriveSessionTitle(text: string): string {
  const firstLine = text.split('\n')[0] ?? ''
  const withoutIds = firstLine.replace(/\b\d{8,}\b/g, '').trim()
  const spaced = withoutIds
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!spaced) return NEW_SESSION_TITLE
  return spaced.length > 24 ? spaced.slice(0, 24) : spaced
}

export function isPendingSessionId(id: string): boolean {
  return id.startsWith('pending-')
}

function normalizeSession(raw: ChassisSession): ChassisSession | null {
  if (!raw || typeof raw.id !== 'string' || typeof raw.label !== 'string') return null
  return {
    id: raw.id,
    backendId: raw.backendId ?? (isPendingSessionId(raw.id) ? null : raw.id),
    label: raw.label,
    time: typeof raw.time === 'string' ? raw.time : '',
    messages: Array.isArray(raw.messages) ? raw.messages : [],
    status: raw.status,
    pinned: Boolean(raw.pinned),
  }
}

export function sortSessions(sessions: ChassisSession[]): ChassisSession[] {
  const pinned = sessions.filter((s) => s.pinned)
  const rest = sessions.filter((s) => !s.pinned)
  return [...pinned, ...rest]
}

export function seedSessions(): ChassisSession[] {
  return taskList.map((item) => ({
    id: item.id,
    backendId: null,
    label: item.label,
    time: item.time,
    messages: item.id === 't-greeting' ? initialMessages : [],
    pinned: item.pinned,
  }))
}

export function readSessions(): ChassisSession[] {
  try {
    const raw = localStorage.getItem(LS_SESSIONS)
    if (!raw) return []
    const parsed = JSON.parse(raw) as ChassisSession[]
    if (!Array.isArray(parsed)) return []
    return parsed.map(normalizeSession).filter((s): s is ChassisSession => s !== null)
  } catch {
    return []
  }
}

export function writeSessions(sessions: ChassisSession[]): void {
  try { localStorage.setItem(LS_SESSIONS, JSON.stringify(sessions)) } catch { /* ignore */ }
}

export function readSelectedId(fallback: string): string {
  try {
    return localStorage.getItem(LS_SELECTED) || fallback
  } catch {
    return fallback
  }
}

export function writeSelectedId(id: string): void {
  try {
    if (id) localStorage.setItem(LS_SELECTED, id)
    else localStorage.removeItem(LS_SELECTED)
  } catch { /* ignore */ }
}

export function summaryToSession(item: SessionSummary): ChassisSession {
  return {
    id: item.session_id || item.id,
    backendId: item.session_id || item.id,
    label: item.title || item.last_message || NEW_SESSION_TITLE,
    time: formatEpoch(item.updated_at || item.created_at),
    messages: [],
    status: item.status,
  }
}

export function mergeSessions(server: ChassisSession[], local: ChassisSession[]): ChassisSession[] {
  const serverIds = new Set(server.map((s) => s.id))
  const extras = local.filter((s) => !serverIds.has(s.id))
  const byLocal = new Map(local.map((s) => [s.id, s]))
  const mergedServer = server.map((s) => {
    const cached = byLocal.get(s.id)
    if (!cached) return s
    return {
      ...s,
      pinned: cached.pinned,
      label: cached.label || s.label,
      messages: cached.messages.length && s.messages.length === 0 ? cached.messages : (s.messages.length ? s.messages : cached.messages),
    }
  })
  return sortSessions([...extras, ...mergedServer])
}

const ANSWER_CONTENT_CALL_KINDS = new Set(['llm_final_response', 'agent_loop_round'])

type ContentMeta = {
  call_id?: unknown
  call_kind?: unknown
  call_state?: unknown
  call_role?: unknown
  answer_visible?: unknown
  trace_kind?: unknown
}

function eventMeta(event: StreamEvent): ContentMeta {
  return (event.metadata ?? {}) as ContentMeta
}

export function cleanThinkingTags(content: string): string {
  if (!content) return ''
  const closed = /`?<\s*(think(?:ing)?)\b[^>]*>`?[\s\S]*?`?<\s*\/\s*\1\s*>`?/gi
  let cleaned = content.replace(closed, '')
  cleaned = cleaned.replace(/`?<\s*think(?:ing)?\b[^>]*>`?[\s\S]*$/gi, '')
  cleaned = cleaned.replace(/`?<\s*\/\s*think(?:ing)?\s*>`?/gi, '')
  return cleaned.trim()
}

export function shouldAppendEventContent(event: StreamEvent): boolean {
  if (event.type !== 'content') return false
  const meta = eventMeta(event)
  if (!meta.call_id) return true
  return ANSWER_CONTENT_CALL_KINDS.has(String(meta.call_kind || ''))
}

export function collectNarrationCallIds(events: StreamEvent[]): Set<string> {
  const ids = new Set<string>()
  for (const event of events) {
    const meta = eventMeta(event)
    if (
      meta.trace_kind === 'call_status' &&
      meta.call_state === 'complete' &&
      meta.call_role === 'narration' &&
      meta.answer_visible !== true &&
      meta.call_id
    ) {
      ids.add(String(meta.call_id))
    }
  }
  return ids
}

export function visibleAnswerFromEvents(events: StreamEvent[]): string {
  const narration = collectNarrationCallIds(events)
  let content = ''
  let result = ''
  for (const event of events) {
    if (event.type === 'result') {
      const text = typeof event.content === 'string' ? event.content : ''
      if (text) result = text
      continue
    }
    if (!shouldAppendEventContent(event)) continue
    const callId = eventMeta(event).call_id
    if (typeof callId === 'string' && callId && narration.has(callId)) continue
    content += typeof event.content === 'string' ? event.content : ''
  }
  return cleanThinkingTags(content || result)
}

export function eventsToBlocks(events: StreamEvent[] | undefined, fallback: string): MessageBlock[] {
  const list = events ?? []
  const lastError = [...list].reverse().find((event) => event.type === 'error')
  if (lastError) {
    const text = typeof lastError.content === 'string' && lastError.content
      ? lastError.content
      : STREAM_FAIL_ERROR
    return [{ type: 'status', title: '错误', content: text }]
  }
  const text = visibleAnswerFromEvents(list)
  if (text) return [{ type: 'text', content: text }]
  const fallbackText = cleanThinkingTags(fallback)
  if (fallbackText) return [{ type: 'text', content: fallbackText }]
  return []
}

export function studentVisibleBlocks(blocks: MessageBlock[]): MessageBlock[] {
  const errors = blocks.filter((block) => block.type === 'status' && block.title === '错误')
  if (errors.length) return errors
  const texts: MessageBlock[] = []
  for (const block of blocks) {
    if (block.type !== 'text' && block.type !== 'code') continue
    const content = block.type === 'text' ? cleanThinkingTags(block.content) : block.content
    if (content.trim()) texts.push({ ...block, content })
  }
  if (texts.length) return texts
  return []
}

export function sessionMessageToChat(message: SessionMessage): ChatMessage {
  const attachments = (message.attachments ?? [])
    .map((item) => item.filename)
    .filter((name): name is string => Boolean(name))
  return {
    id: String(message.id),
    role: message.role,
    author: message.role === 'user' ? 'You' : PRODUCT_NAME,
    time: formatEpoch(message.created_at),
    blocks: message.role === 'user'
      ? [{ type: 'text', content: message.content }]
      : eventsToBlocks(message.events, message.content),
    attachments: attachments.length ? attachments : undefined,
  }
}

export async function loadServerSessions(): Promise<ChassisSession[]> {
  const items = await listSessions()
  return items.map(summaryToSession)
}

export async function loadSessionMessages(sessionId: string, signal?: AbortSignal): Promise<ChatMessage[]> {
  const detail = await getSession(sessionId, signal)
  return (detail.messages ?? []).map(sessionMessageToChat)
}

export function applyStreamEvent(blocks: MessageBlock[], event: StreamEvent): void {
  if (event.type === 'content' && shouldAppendEventContent(event)) {
    const existing = blocks.find((block) => block.type === 'text')
    const chunk = typeof event.content === 'string' ? event.content : ''
    if (existing) existing.content = cleanThinkingTags(existing.content + chunk)
    else if (chunk) blocks.push({ type: 'text', content: cleanThinkingTags(chunk) })
    return
  }
  const next = eventsToBlocks([event], '')
  if (next.length) blocks.splice(0, blocks.length, ...next)
}

export function sessionIdFromEvent(event: StreamEvent): string | undefined {
  if (event.session_id) return event.session_id
  const meta = event.metadata ?? {}
  const fromMeta = meta.session_id
  return typeof fromMeta === 'string' && fromMeta ? fromMeta : undefined
}

export async function fileToAttachment(file: File): Promise<FileAttachment> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
  const comma = dataUrl.indexOf(',')
  const base64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
  return {
    type: 'file',
    filename: file.name,
    mime_type: file.type || undefined,
    base64,
  }
}

export type ViewId = 'chat' | 'new-task' | 'automation' | 'marketplace' | 'my-files' | 'design-system'

export function parseHash(): { view: ViewId; sessionId: string } {
  const raw = (typeof window !== 'undefined' ? window.location.hash : '').replace(/^#/, '')
  const path = raw.startsWith('/') ? raw : `/${raw}`
  if (path.startsWith('/chat/')) {
    return { view: 'chat', sessionId: decodeURIComponent(path.slice('/chat/'.length)) }
  }
  if (path.startsWith('/marketplace')) return { view: 'marketplace', sessionId: '' }
  if (path.startsWith('/automation')) return { view: 'automation', sessionId: '' }
  if (path.startsWith('/files')) return { view: 'my-files', sessionId: '' }
  if (path.startsWith('/design-system')) return { view: 'design-system', sessionId: '' }
  if (path === '/new' || path === '/') return { view: 'new-task', sessionId: '' }
  return { view: 'chat', sessionId: '' }
}

export function hashFor(view: ViewId, sessionId?: string): string {
  if (view === 'marketplace') return '#/marketplace'
  if (view === 'automation') return '#/automation'
  if (view === 'my-files') return '#/files'
  if (view === 'design-system') return '#/design-system'
  if (view === 'new-task' || !sessionId) return '#/new'
  return `#/chat/${encodeURIComponent(sessionId)}`
}

import { apiFetch, apiUrl, expectJson } from './http'
import type { StreamEvent } from './ws'

export interface SessionAttachment {
  type: string
  filename?: string
  base64?: string
  url?: string
  mime_type?: string
}

export interface SessionMessage {
  id: number
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  capability?: string
  events: StreamEvent[]
  attachments: SessionAttachment[]
  created_at: number
}

export interface SessionSummary {
  id: string
  session_id: string
  title: string
  created_at: number
  updated_at: number
  message_count: number
  last_message: string
  status?: string
}

export interface SessionDetail extends SessionSummary {
  messages: SessionMessage[]
}

export async function listSessions(limit = 50, offset = 0): Promise<SessionSummary[]> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  const response = await apiFetch(apiUrl(`/api/v1/sessions?${qs.toString()}`), {
    cache: 'no-store',
  })
  const data = await expectJson<{ sessions: SessionSummary[] }>(response)
  return data.sessions ?? []
}

export async function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionDetail> {
  const response = await apiFetch(apiUrl(`/api/v1/sessions/${sessionId}`), {
    cache: 'no-store',
    signal,
  })
  return expectJson<SessionDetail>(response)
}

export async function renameSession(sessionId: string, title: string): Promise<void> {
  const response = await apiFetch(apiUrl(`/api/v1/sessions/${sessionId}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  await expectJson<{ session?: SessionSummary }>(response)
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await apiFetch(apiUrl(`/api/v1/sessions/${sessionId}`), {
    method: 'DELETE',
  })
  await expectJson<{ deleted: boolean }>(response)
}

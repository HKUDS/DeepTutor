import { apiFetch, apiUrl } from '@/lib/api'
import { activeWorkspaceId } from '@/lib/workspace-scope'
import type { CoWriterDocument, CoWriterDocumentSummary } from '@/lib/co-writer-api'

export interface NoteBlock {
  id: string
  type: string
  props: Record<string, unknown>
  content?: unknown
  children?: NoteBlock[]
}
export interface NotePage extends CoWriterDocument {
  blocks: NoteBlock[] | null
  revision: number
  parent_id: string | null
  icon: string
  cover: string
  pinned: boolean
}
export interface NoteSummary extends CoWriterDocumentSummary {
  parent_id: string | null
  icon: string
  cover?: string
  pinned: boolean
  revision: number
}
export interface NoteSuggestion {
  id: string
  operation: 'insert' | 'replace' | 'delete' | 'comment'
  block_id: string
  markdown: string
  explanation: string
  original: NoteBlock | null
  anchors?: { id: string; side: 'before' | 'after' }[]
  preserve_children?: boolean
  blocks: NoteBlock[] | null
  status: 'pending' | 'accepted' | 'dismissed'
}
export async function noteRequest<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await apiFetch(
    apiUrl(`/api/documents${path}`),
    body === undefined
      ? { cache: 'no-store' }
      : {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
  )
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail || `Request failed (${response.status})`)
  }
  return response.json()
}

export async function exportNoteFlashcards(docId?: string): Promise<Blob> {
  const path = docId
    ? `/api/documents/${encodeURIComponent(docId)}/flashcards/export`
    : `/api/documents/flashcards/export`
  const response = await apiFetch(apiUrl(path), { cache: 'no-store' })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const message =
      typeof detail?.detail === 'string' ? detail.detail : `Request failed (${response.status})`
    throw new Error(message)
  }
  return response.blob()
}

export const getNote = (id: string) => noteRequest<NotePage>(`/${id}`)

// Notes belong to the active workspace; cache them per workspace so a revisit
// (or a route-group remount) paints the last list instantly instead of a
// skeleton, and a workspace switch never shows another workspace's pages.
const notesListCache = new Map<string, NoteSummary[]>()

export function peekCachedNotes(workspaceId = activeWorkspaceId()): NoteSummary[] | null {
  if (typeof window === 'undefined') return null
  return notesListCache.get(workspaceId) ?? null
}

export async function listNotes(): Promise<{ documents: NoteSummary[] }> {
  const scope = activeWorkspaceId()
  const result = await noteRequest<{ documents: NoteSummary[] }>('')
  if (typeof window !== 'undefined') {
    notesListCache.set(scope, result.documents)
  }
  return result
}
export const saveNote = (id: string, patch: Partial<NotePage> & { expected_revision: number }) =>
  noteRequest<NotePage>(`/${id}`, patch, 'PUT')
export const createNote = (title = '', parent_id: string | null = null, content = '') =>
  noteRequest<NotePage>('', { title, parent_id, content, ...(content ? {} : { blocks: [] }) })
export const getSuggestions = (id: string) =>
  noteRequest<{ suggestions: NoteSuggestion[] }>(`/${id}/suggestions`)
export const reviewSuggestion = (
  id: string,
  suggestionId: string,
  accept: boolean,
  blocks?: NoteBlock[]
) => noteRequest<NotePage>(`/${id}/suggestions/${suggestionId}`, { accept, blocks })

/** A conversation held at one line of the page. The session keeps the
 *  transcript; the page keeps where it belongs. */
export interface NoteThread {
  session_id: string
  block_id: string
  quote: string
  origin: 'ask' | 'generate'
  created_at: number
  title: string
  status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled' | 'rejected'
  updated_at: number
  message_count: number
  last_message: string
}
export const listThreads = (id: string) =>
  noteRequest<{ threads: NoteThread[] }>(`/${id}/threads`)
export const anchorThread = (
  id: string,
  thread: Pick<NoteThread, 'session_id' | 'block_id'> & Partial<Pick<NoteThread, 'quote' | 'origin'>>
) => noteRequest<NoteThread>(`/${id}/threads`, thread)
export const deleteThread = (id: string, sessionId: string) =>
  noteRequest<{ deleted: boolean }>(`/${id}/threads/${encodeURIComponent(sessionId)}`, {}, 'DELETE')

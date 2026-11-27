import { apiFetch } from '@/shared/api/client'
import { activeWorkspaceId, scopedUrl } from '@/lib/workspace-scope'

export type TaskStatus = 'todo' | 'doing' | 'done'
export type TaskColors = Record<TaskStatus, string>
export const DEFAULT_TASK_COLORS: TaskColors = {
  todo: '#2563eb',
  doing: '#a16207',
  done: '#15803d',
}

export interface TaskCard {
  id: string
  title: string
  note: string
  status: TaskStatus
  archived: boolean
  created_at: string
  updated_at: string
  workspace_id: string | null
  /** A plain local calendar day ("YYYY-MM-DD"), never shifted through UTC. */
  due_date: string | null
}
export interface SessionTaskLinks {
  workspace_id: string
  session_id: string
  task_ids: string[]
  status_link_enabled: boolean
}
export interface TaskBoard {
  cards: TaskCard[]
  colors: TaskColors
  session_links: SessionTaskLinks[]
  revision: number
}

const endpoint = '/api/task-board'
const listeners = new Set<(board: TaskBoard, workspaceId: string) => void>()
export function subscribeTaskBoardChanges(listener: (board: TaskBoard, workspaceId: string) => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
export function normalizeTaskBoard(board: TaskBoard): TaskBoard {
  return {
    ...board,
    colors: board.colors ?? DEFAULT_TASK_COLORS,
    session_links: board.session_links ?? [],
    revision: board.revision ?? 0,
  }
}
export function publishTaskBoard(board: TaskBoard, workspaceId = activeWorkspaceId()) {
  listeners.forEach(listener => listener(normalizeTaskBoard(board), workspaceId))
}
export function taskBoardUrl(path = '', workspaceId = activeWorkspaceId()) {
  return scopedUrl(`${endpoint}${path}`, workspaceId)
}

async function request(
  path: string,
  init?: RequestInit,
  workspaceId = activeWorkspaceId()
): Promise<TaskBoard> {
  const response = await apiFetch(taskBoardUrl(path, workspaceId), init)
  if (!response.ok) throw new Error('Task board request failed')
  const board = normalizeTaskBoard(await response.json())
  // A response belongs to the workspace selected when the request started.
  if (init?.method) publishTaskBoard(board, workspaceId)
  return board
}
export function getTaskBoard(signal?: AbortSignal, workspaceId = activeWorkspaceId()): Promise<TaskBoard> {
  return request('', { signal, cache: 'no-store' }, workspaceId)
}
export function createTaskCard(
  title: string,
  options: { due_date?: string | null } = {}
): Promise<TaskBoard> {
  return request('/cards', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(
      options.due_date !== undefined ? { title, due_date: options.due_date } : { title }
    ),
  })
}
export function updateTaskCard(
  id: string,
  changes: Partial<
    Pick<TaskCard, 'title' | 'note' | 'status' | 'archived' | 'workspace_id' | 'due_date'>
  >
): Promise<TaskBoard> {
  return request(`/cards/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  })
}
export function updateTaskColors(colors: TaskColors): Promise<TaskBoard> {
  return request('/colors', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(colors),
  })
}
export function linkSessionTasks(
  sessionId: string,
  workspaceId: string,
  taskIds: string[]
): Promise<TaskBoard> {
  return request(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: workspaceId, task_ids: taskIds }),
  }, workspaceId)
}
export function setTaskStatusLink(
  sessionId: string,
  workspaceId: string,
  enabled: boolean
): Promise<TaskBoard> {
  return request(`/sessions/${encodeURIComponent(sessionId)}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: workspaceId, enabled }),
  }, workspaceId)
}
export function sessionTaskLinks(
  board: TaskBoard | null,
  sessionId: string | null,
  workspaceId: string
): SessionTaskLinks | undefined {
  return board?.session_links.find(
    row => row.session_id === sessionId && row.workspace_id === workspaceId
  )
}
export function sessionTaskColor(
  board: TaskBoard | null,
  sessionId: string,
  workspaceId: string
): string | undefined {
  const links = sessionTaskLinks(board, sessionId, workspaceId)
  if (!links || !links.status_link_enabled) return undefined
  const card = board?.cards.find(card => card.id === links.task_ids.at(-1))
  return card ? board?.colors[card.status] : undefined
}

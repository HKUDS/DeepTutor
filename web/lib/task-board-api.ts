import { apiFetch, apiUrl } from '@/shared/api/client'

export type TaskStatus = 'todo' | 'doing' | 'done'

export interface TaskCard {
  id: string
  title: string
  note: string
  status: TaskStatus
  archived: boolean
  created_at: string
  updated_at: string
}

export interface TaskBoard {
  cards: TaskCard[]
}

const endpoint = '/api/task-board'

async function request(path: string, init?: RequestInit): Promise<TaskBoard> {
  const response = await apiFetch(apiUrl(path), init)
  if (!response.ok) throw new Error('Task board request failed')
  return response.json() as Promise<TaskBoard>
}

export function getTaskBoard(signal?: AbortSignal): Promise<TaskBoard> {
  return request(endpoint, { signal, cache: 'no-store' })
}

export function createTaskCard(title: string): Promise<TaskBoard> {
  return request(`${endpoint}/cards`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
}

export function updateTaskCard(
  id: string,
  changes: Partial<Pick<TaskCard, 'title' | 'note' | 'status' | 'archived'>>
): Promise<TaskBoard> {
  return request(`${endpoint}/cards/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  })
}

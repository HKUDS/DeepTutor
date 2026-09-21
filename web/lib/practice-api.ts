import { scopedUrl } from '@/lib/workspace-scope'
import { apiFetch, apiUrl } from '@/lib/api'
import type { NotebookEntry } from '@/lib/notebook-api'

const ROOT = '/api/question-notebook/practice'
export type PracticeRating = 'again' | 'hard' | 'good' | 'easy'
export interface PracticeSummary {
  total: number
  mistakes: number
  due: number
  overdue: number
  reviewed_today: number
  next_due_at: number | null
  day_end: number
  timezone: string
  unavailable_workspaces?: string[]
}
export interface PracticeRef {
  id: number
  content_workspace_id?: string
  content_workspace_name?: string
}
export interface PracticeQuestion {
  content_workspace_id?: string
  content_workspace_name?: string
  entry: NotebookEntry
  state: { version: number; review_count: number; is_mistake: boolean; due_at: number | null }
}
export type PracticeMetric = 'questions' | 'mistakes' | 'reviews'
export type PracticeCounts = Record<PracticeMetric, number>
export interface PracticeAnalytics {
  timezone: string
  days: number
  start_date: string
  end_date: string
  updated_at: number
  daily: (PracticeCounts & { date: string })[]
  sources: (PracticeCounts & { source: string })[]
  totals: PracticeCounts
}
export const getPracticeAnalytics = (courseId = '', days = 30, workspaceId?: string) =>
  request<PracticeAnalytics>(
    `/analytics?${params(courseId)}&days=${days}&all_workspaces=${workspaceId === '*'}`,
    undefined,
    workspaceId === '*' ? '' : workspaceId
  )
export interface ImportPreview {
  token: string | null
  total: number
  valid: number
  errors: { row: number; message: string }[]
  samples: { question: string; question_type: string; correct_answer: string; tags: string[] }[]
}
export class PracticeRequestError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message)
  }
}
async function request<T>(path: string, init?: RequestInit, workspaceId?: string): Promise<T> {
  const response = await apiFetch(
    apiUrl(workspaceId === undefined ? `${ROOT}${path}` : scopedUrl(`${ROOT}${path}`, workspaceId)),
    { cache: 'no-store', ...init }
  )
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new PracticeRequestError(
      typeof body.detail === 'string' ? body.detail : `Request failed: ${response.status}`,
      response.status
    )
  }
  return response.json() as Promise<T>
}
const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
function params(courseId = ''): string {
  return new URLSearchParams({
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    course_id: courseId,
  }).toString()
}
export const getPracticeSummary = (courseId = '', workspaceId?: string) =>
  request<PracticeSummary>(
    `/summary?${params(courseId)}&all_workspaces=${workspaceId === '*'}`,
    undefined,
    workspaceId === '*' ? '' : workspaceId
  )
export const getPracticeQueue = (courseId = '', workspaceId?: string) =>
  request<PracticeQuestion[]>(
    `/queue?${params(courseId)}&all_workspaces=${workspaceId === '*'}`,
    undefined,
    workspaceId === '*' ? '' : workspaceId
  )
export const getPracticeQuestion = (id: number, workspaceId?: string) =>
  request<PracticeQuestion>(`/questions/${id}`, undefined, workspaceId)
export const checkPracticeAnswer = (id: number, answer: string, workspaceId?: string) =>
  request<{ correct: boolean | null }>(`/questions/${id}/check`, json({ answer }), workspaceId)
export const savePracticeReview = (
  id: number,
  body: {
    request_id: string
    version: number
    rating: PracticeRating
    answer: string
    self_report?: boolean
  },
  workspaceId?: string
) =>
  request<{ due_at: number; correct: boolean | null; rating: PracticeRating; is_mistake: boolean }>(
    `/questions/${id}/review`,
    json(body),
    workspaceId
  )
export function previewPracticeImport(file: File, target: 'bank' | 'mistakes', courseId = '') {
  const data = new FormData()
  data.append('file', file)
  data.append('target', target)
  data.append('course_id', courseId)
  return request<ImportPreview>('/import/preview', { method: 'POST', body: data })
}
export const commitPracticeImport = (token: string) =>
  request<{ created: number; duplicates: number }>('/import/commit', json({ token }))
export async function downloadPracticeTemplate(format: 'csv' | 'xlsx') {
  const response = await apiFetch(apiUrl(`${ROOT}/import/template?format=${format}`))
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `practice-template.${format}`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

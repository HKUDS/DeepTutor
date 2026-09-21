import { apiFetch, apiUrl } from '@/lib/api'
import { scopedUrl } from '@/lib/workspace-scope'

export interface LearningOrigin {
  content_workspace_id?: string
  content_workspace_name?: string
}
export const libraryItemKey = (row: LearningOrigin, id: string | number) =>
  JSON.stringify([row.content_workspace_id ?? '', id])

export async function learningLibrary<T extends LearningOrigin>(kind: string) {
  const response = await apiFetch(apiUrl(scopedUrl(`/api/dashboard/learning-library/${kind}`, '')), { cache: 'no-store' })
  if (!response.ok) throw new Error(`Could not load learning library (${response.status})`)
  return await response.json() as { items: T[]; unavailable_workspaces: string[]; can_create: boolean }
}

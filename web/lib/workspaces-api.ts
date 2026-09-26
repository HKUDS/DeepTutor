import { apiFetch, apiUrl } from '@/lib/api'
import { invalidateClientCache, withClientCache } from '@/lib/client-cache'
import { notifySessionsChanged } from '@/lib/session-events'

export interface WorkspaceResources {
  skills: string[] | null
  mcp: string[] | null
  knowledge_bases: string[] | null
}

export const inheritedWorkspaceResources = (): WorkspaceResources => ({
  skills: null,
  mcp: null,
  knowledge_bases: null,
})

export interface WorkspaceResourceOption {
  id: string
  name: string
  description?: string
  source?: string
  provenance_label?: string
  available?: boolean
}
export type WorkspaceResourceCatalog = Record<keyof WorkspaceResources, WorkspaceResourceOption[]>

export function getWorkspaceResources(workspaceId = ''): Promise<WorkspaceResourceCatalog> {
  return request(
    `/api/settings/workspace/resources?workspace_id=${encodeURIComponent(workspaceId)}`
  )
}

export interface ChatWorkspaceRegistration {
  resources?: WorkspaceResources
  workspace_id: string
  kind: 'system' | 'general' | 'workspace'
  follows_root: boolean
  display_name: string
  path: string
  archived: boolean
  created_at: string
  status: 'ready' | 'invalid'
  error: string
}

const endpoint = '/api/settings/workspace/registrations'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(apiUrl(url), init)
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`)
  return payload as T
}

export function listWorkspaces(force = false): Promise<ChatWorkspaceRegistration[]> {
  return withClientCache(
    'workspaces:list',
    async () => {
      const result = await request<{ workspaces: ChatWorkspaceRegistration[] }>(endpoint)
      return result.workspaces
    },
    { force, ttlMs: 15_000 }
  )
}

export async function saveWorkspace(
  input: { name?: string; path?: string; archived?: boolean; resources?: WorkspaceResources },
  workspaceId?: string
): Promise<ChatWorkspaceRegistration> {
  const result = await request<{ workspace: ChatWorkspaceRegistration }>(
    workspaceId ? `${endpoint}/${encodeURIComponent(workspaceId)}` : endpoint,
    {
      method: workspaceId ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }
  )
  invalidateClientCache('workspaces:')
  invalidateClientCache('knowledge:')
  notifySessionsChanged()
  return result.workspace
}

export function workspaceChatHref(workspaceId: string): string {
  return `/chat?dt_workspace=${encodeURIComponent(workspaceId)}`
}

export interface WorkspaceCatalog {
  root: string
  workspaces: ChatWorkspaceRegistration[]
  migration?: { id: string } | null
}

export interface SystemWorkspaceSnapshot {
  generated_at: string
  models: Record<
    string,
    {
      active_profile_id?: string
      active_model_id?: string
      profiles: {
        id?: string
        name?: string
        binding?: string
        endpoint_origin?: string
        models: { id?: string; name?: string; model?: string }[]
      }[]
    }
  >
  mcp: { name: string; enabled: boolean; transport: string; endpoint_origin: string }[]
}

export function getWorkspaceCatalog(): Promise<WorkspaceCatalog> {
  return request<WorkspaceCatalog>(endpoint)
}

export async function migrateWorkspace(
  path: string,
  workspaceId?: string
): Promise<WorkspaceCatalog> {
  const result = await request<WorkspaceCatalog>(
    workspaceId
      ? `${endpoint}/${encodeURIComponent(workspaceId)}/migrate`
      : `${endpoint}/migrate-root`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }
  )
  invalidateClientCache('workspaces:')
  invalidateClientCache('knowledge:')
  notifySessionsChanged()
  return result
}

export function getSystemWorkspaceSnapshot(): Promise<SystemWorkspaceSnapshot> {
  return request<SystemWorkspaceSnapshot>(`${endpoint}/system-snapshot`, { method: 'POST' })
}

export function workspaceLabel(row: ChatWorkspaceRegistration, zh: boolean): string {
  if (row.kind === 'system') return zh ? '系统工作区' : 'System workspace'
  if (row.kind === 'general') return zh ? '通用工作区' : 'General workspace'
  return row.display_name
}

export async function resourceUsage(
  kind: keyof WorkspaceResources,
  resourceId: string,
  skillWorkspace = ''
): Promise<string[]> {
  const params = new URLSearchParams({
    kind,
    resource_id: resourceId,
    skill_workspace: skillWorkspace,
  })
  const result = await request<{ workspaces: { display_name: string }[] }>(
    `/api/settings/workspace/resource-usage?${params}`
  )
  return result.workspaces.map(row => row.display_name)
}

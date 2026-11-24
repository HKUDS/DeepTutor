'use client'

import { usePathname } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { useActiveWorkspaceId } from '@/hooks/useActiveWorkspaceId'
import { useChatWorkspaces } from '@/hooks/useChatWorkspaces'
import { selectWorkspace } from '@/lib/workspace-scope'
import { switchDestination } from '@/components/sidebar/page-sections'

/** The workspace this URL is scoped to, the ones it can switch to, and the switch. */
export function useWorkspaceChoices() {
  const { t } = useTranslation()
  const pathname = usePathname() ?? '/'
  const active = useActiveWorkspaceId()
  const { workspaces, loaded } = useChatWorkspaces()
  const current = workspaces.find(row => row.workspace_id === active)
  // Before the first fetch settles there is no evidence the workspace is
  // gone, so an empty label — not "Workspace unavailable" — keeps the header
  // from flashing a wrong state on every route-group remount.
  const currentName = active
    ? (current?.display_name ?? (loaded ? t('Workspace unavailable') : ''))
    : t('General workspace')
  const choices = [
    { workspace_id: '', display_name: t('General workspace') },
    ...workspaces.filter(row => row.workspace_id === active || (!row.archived && row.status === 'ready')),
  ]
  const choose = (workspaceId: string) => {
    if (workspaceId !== active) void selectWorkspace(workspaceId, switchDestination(pathname))
  }
  return { active, currentName, choices, choose }
}

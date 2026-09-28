'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { FolderOpen, Settings2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatWorkspaces } from '@/hooks/useChatWorkspaces'
import { selectWorkspace } from '@/lib/workspace-scope'

export function WorkspaceSwitcher() {
  const { t } = useTranslation()
  const { workspaces, error } = useChatWorkspaces()
  const query = useSearchParams()
  const active = query.get('dt_workspace') ?? query.get('workspace') ?? ''
  const [draftError, setDraftError] = useState(false)
  useEffect(() => {
    const failed = () => setDraftError(true)
    window.addEventListener('deeptutor:workspace-switch-error', failed)
    return () => window.removeEventListener('deeptutor:workspace-switch-error', failed)
  }, [])
  return (
    <div className="mx-3 mb-2 rounded-lg border border-[var(--border)] px-2 py-1.5">
      <div className="flex items-center gap-2">
        <FolderOpen size={14} className="shrink-0 text-[var(--muted-foreground)]" />
        <select
          aria-label={t('Active workspace')}
          value={active}
          onChange={event => selectWorkspace(event.target.value)}
          className="min-w-0 flex-1 bg-transparent py-1 text-xs text-[var(--foreground)] outline-none"
        >
          <option value="">{t('Default workspace')}</option>
          {active && !workspaces.some(row => row.workspace_id === active) ? (
            <option value={active}>{t('Workspace unavailable')}</option>
          ) : null}
          {workspaces
            .filter(row => !row.archived || row.workspace_id === active)
            .map(row => (
              <option
                key={row.workspace_id}
                value={row.workspace_id}
                disabled={row.status !== 'ready'}
              >
                {row.display_name}
                {row.archived ? ` (${t('Archived')})` : ''}
              </option>
            ))}
        </select>
        <Link
          href="/settings/workspace"
          aria-label={t('Manage workspaces')}
          className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <Settings2 size={13} />
        </Link>
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-xs text-[var(--destructive)]">
          {error}
        </p>
      ) : null}
      {draftError ? (
        <p role="alert" className="mt-1 text-xs text-[var(--destructive)]">
          {t('Could not save the draft. Free browser storage before switching workspaces.')}
        </p>
      ) : null}
    </div>
  )
}

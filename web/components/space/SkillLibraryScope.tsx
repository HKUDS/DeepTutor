'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { listWorkspaces, type ChatWorkspaceRegistration } from '@/lib/workspaces-api'

export function SkillLibraryScope() {
  const { t } = useTranslation()
  const search = useSearchParams()
  const scope = search.get('skill_workspace') ?? ''
  const [workspaces, setWorkspaces] = useState<ChatWorkspaceRegistration[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    listWorkspaces()
      .then(rows => {
        if (active) setWorkspaces(rows.filter(row => row.kind === 'workspace' && !row.archived))
      })
      .catch(err => {
        if (active) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      active = false
    }
  }, [])
  return (
    <div className="mb-5 space-y-2">
      <label className="flex flex-wrap items-center gap-3 text-sm">
        {t('Skill library')}
        <select
          className="max-w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2"
          value={scope}
          onChange={event => {
            const url = new URL(window.location.href)
            if (event.target.value) url.searchParams.set('skill_workspace', event.target.value)
            else url.searchParams.delete('skill_workspace')
            window.location.assign(url.toString())
          }}
        >
          <option value="">{t('Account shared skills')}</option>
          {workspaces.map(row => (
            <option key={row.workspace_id} value={row.workspace_id}>
              {row.display_name}
            </option>
          ))}
          {scope && !workspaces.some(row => row.workspace_id === scope) && (
            <option value={scope}>{scope}</option>
          )}
        </select>
      </label>
      <p className="text-xs text-[var(--muted-foreground)]">
        {scope
          ? t(
              'Skills created here belong to this workspace. Same-name skills override shared versions when enabled.'
            )
          : t('Shared skills can be assigned to multiple workspaces.')}
      </p>
      {error && (
        <p role="alert" className="text-xs text-[var(--destructive)]">
          {error}
        </p>
      )}
    </div>
  )
}

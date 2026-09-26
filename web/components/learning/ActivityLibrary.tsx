'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { learningLibrary, libraryItemKey, type LearningOrigin } from '@/lib/learning-library'
import { activeWorkspaceId, scopedUrl } from '@/lib/workspace-scope'
import { watchingRoute } from '@/lib/learning-routes'
import { LearningShell, LearningErrorState, LearningSkeleton, LearningEmptyState } from './LearningShell'
import { useLearningCreation, useLibraryFilter, WorkspaceLabel } from './LibraryWorkspace'

interface Activity extends LearningOrigin {
  id?: number
  session_id?: string
  title?: string
  question?: string
  updated_at?: number
}

/** All-account discovery; opening an item binds subsequent interaction to its store. */
export function ActivityLibrary({ kind, onCreate }: { kind: 'practice' | 'watching'; onCreate: () => void }) {
  const { t } = useTranslation()
  const router = useRouter()
  const [items, setItems] = useState<Activity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [revision, setRevision] = useState(0)
  const { rows, control } = useLibraryFilter(items)
  const creation = useLearningCreation(onCreate)
  useEffect(() => {
    let alive = true
    void learningLibrary<Activity>(kind).then(result => {
      if (!alive) return
      setItems(result.items)
      setError(result.unavailable_workspaces.length ? t('Some workspaces could not be loaded. Available content is shown.') : '')
    }).catch(() => { if (alive) setError(t('Could not load learning records.')) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [kind, revision, t])
  const matches = rows.filter(row => (row.title || row.question || '').toLowerCase().includes(query.toLowerCase()))
  const stores = [...new Map(rows.map(row => [row.content_workspace_id ?? '', row])).values()]
  return <LearningShell title={t(kind === 'practice' ? 'Practice' : 'Immersive Watching')}
    subtitle={t('Browse all your learning records. Continue where each one was created.')}
    action={<button type="button" onClick={creation.begin} className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">{t(kind === 'practice' ? 'Import questions' : 'New watching session')}</button>}>
    {creation.dialog}
    <div className="mb-6 flex flex-wrap items-center gap-3">{control}<input aria-label={t('Search learning records')} placeholder={t('Search learning records')} value={query} onChange={event => setQuery(event.target.value)} className="h-9 min-w-0 rounded-lg border border-border bg-background px-3 text-sm" /></div>
    {kind === 'practice' && <div className="mb-5 flex flex-wrap gap-2">
      {stores.map(row => <Link key={row.content_workspace_id ?? ''} href={scopedUrl('/learning/practice?store=1', row.content_workspace_id ?? '')} className="rounded-lg border border-border px-3 py-2 text-xs">
        <WorkspaceLabel row={row} /> · {t('Review and manage')}
      </Link>)}
      {!stores.length && !loading && <button onClick={() => router.push(scopedUrl('/learning/practice?store=1', activeWorkspaceId()))} className="text-sm underline">{t('Review and manage')}</button>}
    </div>}
    {error && <LearningErrorState message={error} onRetry={() => setRevision(value => value + 1)} />}
    {loading ? <LearningSkeleton /> : !matches.length ? <LearningEmptyState title={t('No matching learning records')} description={t('Try another workspace filter or create new content.')} /> :
      <div className="divide-y divide-border">{matches.map(row => <Link key={libraryItemKey(row, row.session_id ?? row.id ?? '')}
        href={kind === 'watching' ? watchingRoute(row.session_id, row.content_workspace_id ?? '') : scopedUrl(`/learning/practice?store=1&question=${row.id}`, row.content_workspace_id ?? '')}
        className="block rounded-lg px-3 py-4 hover:bg-muted">
        <div className="mb-1 line-clamp-2 text-sm font-medium">{row.title || row.question || t('New chat')}</div>
        <WorkspaceLabel row={row} />
      </Link>)}</div>}
  </LearningShell>
}

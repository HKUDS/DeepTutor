'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import Modal from '@/components/common/Modal'
import { useChatWorkspaces } from '@/hooks/useChatWorkspaces'
import { activeWorkspaceId, scopedUrl } from '@/lib/workspace-scope'
import type { LearningOrigin } from '@/lib/learning-library'

export function workspaceName(row: LearningOrigin, t: TFunction) {
  return row.content_workspace_name || row.content_workspace_id || t('Default workspace')
}

export function WorkspaceLabel({ row }: { row: LearningOrigin }) {
  const { t } = useTranslation()
  return <span className="text-xs text-muted-foreground">{workspaceName(row, t)}</span>
}

export function useLibraryFilter<T extends LearningOrigin>(rows: T[]) {
  const [filter, setFilter] = useState('*')
  const { t } = useTranslation()
  const options = new Map(rows.map(row => [row.content_workspace_id ?? '', workspaceName(row, t)]))
  // A workspace that no longer has rows cannot stay selected: its option is
  // gone, so nothing on screen would say why the list is empty.
  const active = filter !== '*' && options.has(filter) ? filter : '*'
  const control = <label className="inline-flex max-w-full shrink-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
    {t('Show materials from')}
    <select aria-label={t('Filter by workspace')} value={active} onChange={event => setFilter(event.target.value)} className="h-9 min-w-0 max-w-56 rounded-lg border border-border bg-background px-3 text-sm text-foreground">
      <option value="*">{t('All workspaces')}</option>
      {[...options].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
    </select>
  </label>
  // The same choice sized for a page's own toolbar row. With one workspace
  // there is nothing to choose between, so it is not shown at all.
  const picker = options.size > 1
    ? <select aria-label={t('Filter by workspace')} value={active} onChange={event => setFilter(event.target.value)} className="h-8 min-w-0 max-w-44 rounded-lg border border-border bg-background px-2 text-[12px] text-foreground">
      <option value="*">{t('All workspaces')}</option>
      {[...options].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
    </select>
    : null
  return {
    rows: active === '*' ? rows : rows.filter(row => (row.content_workspace_id ?? '') === active),
    control,
    picker,
    // More than one workspace on screen at once: rows need to say whose they are.
    mixed: active === '*' && options.size > 1,
  }
}

/** Opens creation when a link arrives with `?create=1`, then drops the flag from the URL. */
export function useCreateRequest(open: () => void) {
  const router = useRouter()
  const pathname = usePathname()
  const query = useSearchParams()
  const openRef = useRef(open)
  useEffect(() => { openRef.current = open }, [open])
  const consumed = useRef(false)
  useEffect(() => {
    if (query.get('create') !== '1') { consumed.current = false; return }
    if (consumed.current) return
    consumed.current = true
    openRef.current()
    const next = new URLSearchParams(query.toString())
    next.delete('create')
    router.replace(`${pathname}${next.size ? `?${next}` : ''}`, { scroll: false })
  }, [pathname, query, router])
}

/** Pick a destination only when creating; URL scopes all ensuing uploads and writes. */
export function useLearningCreation(open: () => void) {
  const router = useRouter()
  const pathname = usePathname()
  const query = useSearchParams()
  useCreateRequest(open)
  const { t } = useTranslation()
  const { workspaces, error } = useChatWorkspaces()
  const [choosing, setChoosing] = useState(false)
  const [destination, setDestination] = useState(activeWorkspaceId)
  const dialog = <Modal isOpen={choosing} onClose={() => setChoosing(false)} title={t('Save new content to')} width="sm">
    <div className="p-5">
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">{t('Only new content is saved here. Your existing materials remain visible in all workspaces.')}</p>
      <select aria-label={t('Save to workspace')} value={destination} onChange={event => setDestination(event.target.value)} className="mt-3 h-9 w-full rounded-lg border border-border bg-background px-2.5 text-[13px] outline-none focus:border-ring">
        <option value="">{t('Default workspace')}</option>
        {workspaces.filter(row => !row.archived && row.status === 'ready').map(row => <option key={row.workspace_id} value={row.workspace_id}>{row.display_name}</option>)}
      </select>
      {error && <p role="alert" className="mt-3 text-[11.5px] text-destructive">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className="h-8 rounded-lg px-3 text-[12px] text-muted-foreground hover:bg-muted" onClick={() => setChoosing(false)}>{t('Cancel')}</button>
        <button type="button" className="h-8 rounded-lg bg-primary px-3.5 text-[12px] font-semibold text-primary-foreground hover:opacity-90" onClick={() => {
          setChoosing(false)
          if (destination === activeWorkspaceId()) open()
          else {
            const next = new URLSearchParams(query.toString())
            next.delete('dt_workspace'); next.delete('workspace'); next.set('create', '1')
            router.push(scopedUrl(`${pathname}?${next}`, destination))
          }
        }}>{t('Continue')}</button>
      </div>
    </div>
  </Modal>
  // Course-created content inherits the course store so its references stay valid.
  return { begin: () => query.has("course") ? open() : setChoosing(true), dialog }
}

export function requestedLearningCreation() {
  return typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('create') === '1'
}

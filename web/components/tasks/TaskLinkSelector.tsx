'use client'

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { linkSessionTasks, sessionTaskLinks } from '@/lib/task-board-api'
import { useTaskBoard } from '@/lib/task-board-store'

export default function TaskLinkSelector({
  sessionId,
  workspaceId,
  draftTaskIds = [],
  onDraftChange,
  onLinked,
}: {
  sessionId?: string | null
  workspaceId: string
  draftTaskIds?: string[]
  onDraftChange?: (ids: string[]) => void
  onLinked?: () => void
}) {
  const { t } = useTranslation()
  const { board, error } = useTaskBoard()
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [saveError, setSaveError] = useState(false)
  const ids = sessionId
    ? (sessionTaskLinks(board, sessionId, workspaceId)?.task_ids ?? [])
    : draftTaskIds
  const cards =
    board?.cards.filter(
      card =>
        (!card.archived || ids.includes(card.id)) &&
        `${card.title} ${card.note}`.toLowerCase().includes(query.toLowerCase())
    ) ?? []

  async function toggle(id: string) {
    const next = ids.includes(id) ? ids.filter(value => value !== id) : [...ids, id]
    if (!sessionId) {
      onDraftChange?.(next)
      onLinked?.()
      return
    }
    setBusy(true)
    setSaveError(false)
    try {
      await linkSessionTasks(sessionId, workspaceId, next)
      onLinked?.()
    } catch {
      setSaveError(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-2 p-3">
      <input
        aria-label={t('tasks.search')}
        placeholder={t('tasks.search')}
        value={query}
        onChange={event => setQuery(event.target.value)}
        className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
      />
      {(error || saveError) && (
        <p role="alert" className="text-xs text-[var(--destructive)]">
          {t('tasks.saveError')}
        </p>
      )}
      {!board && !error && (
        <p role="status" className="text-sm text-[var(--muted-foreground)]">
          {t('kanban.loading')}
        </p>
      )}
      {board && !cards.length && (
        <p className="py-3 text-sm text-[var(--muted-foreground)]">{t('tasks.empty')}</p>
      )}
      <div className="max-h-72 space-y-1 overflow-y-auto">
        {cards.map(card => (
          <label
            key={card.id}
            className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-2 hover:bg-[var(--accent)]"
          >
            <input
              type="checkbox"
              disabled={busy || (!sessionId && !onDraftChange)}
              checked={ids.includes(card.id)}
              onChange={() => void toggle(card.id)}
              className="mt-1 shrink-0"
            />
            <span
              className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: board?.colors[card.status] }}
            />
            <span className="min-w-0 flex-1 break-words text-sm">
              {card.title}
              <span className="block text-xs text-[var(--muted-foreground)]">
                {t(`kanban.${card.status}`)}
                {card.archived ? ` · ${t('Archive')}` : ''}
              </span>
            </span>
          </label>
        ))}
      </div>
      <p className="text-xs text-[var(--muted-foreground)]">{t('tasks.latestHint')}</p>
    </div>
  )
}

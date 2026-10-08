'use client'

import { useState } from 'react'
import Link from 'next/link'
import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  linkSessionTasks,
  sessionTaskLinks,
  updateTaskCard,
  type TaskCard,
  type TaskStatus,
} from '@/lib/task-board-api'
import { useTaskBoard } from '@/lib/task-board-store'
import { activeWorkspaceId } from '@/lib/workspace-scope'

export default function TaskPanelSection({
  sessionId,
  draftTaskIds = [],
  onDraftChange,
}: {
  sessionId: string | null
  draftTaskIds?: string[]
  onDraftChange?: (ids: string[]) => void
}) {
  const { t } = useTranslation()
  const { board } = useTaskBoard()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const workspaceId = activeWorkspaceId()
  const ids = sessionId
    ? (sessionTaskLinks(board, sessionId, workspaceId)?.task_ids ?? [])
    : draftTaskIds
  const linked = [...ids].reverse().flatMap(id => board?.cards.find(card => card.id === id) ?? [])
  const assigned =
    board?.cards.filter(
      card => !card.archived && card.workspace_id === workspaceId && !ids.includes(card.id)
    ) ?? []
  if (!linked.length && !assigned.length) return null

  async function save(operation: () => Promise<unknown>) {
    setBusy(true)
    setError(false)
    try {
      await operation()
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }
  function rows(cards: TaskCard[], allowUnlink: boolean) {
    return cards.map(card => (
      <div key={card.id} className="space-y-1 rounded-xl bg-[var(--muted)] p-3">
        <div className="flex items-start gap-2">
          <span
            className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: board?.colors[card.status] }}
          />
          <span className="min-w-0 flex-1 break-words text-sm font-medium">{card.title}</span>
          {allowUnlink && (sessionId || onDraftChange) && (
            <button
              type="button"
              disabled={busy}
              aria-label={`${card.title}: ${t('tasks.unlink')}`}
              onClick={() => {
                const next = ids.filter(id => id !== card.id)
                if (sessionId) void save(() => linkSessionTasks(sessionId, workspaceId, next))
                else onDraftChange?.(next)
              }}
              className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
            >
              <X size={14} />
            </button>
          )}
        </div>
        {card.note && (
          <p className="whitespace-pre-wrap break-words text-xs text-[var(--muted-foreground)]">
            {card.note}
          </p>
        )}
        <select
          aria-label={`${card.title}: ${t('tasks.status')}`}
          value={card.status}
          disabled={busy}
          onChange={event =>
            void save(() => updateTaskCard(card.id, { status: event.target.value as TaskStatus }))
          }
          className="rounded-md bg-[var(--card)] px-2 py-1 text-xs"
        >
          {(['todo', 'doing', 'done'] as const).map(status => (
            <option key={status} value={status}>
              {t(`kanban.${status}`)}
            </option>
          ))}
        </select>
        {card.archived && (
          <span className="ml-2 text-xs text-[var(--muted-foreground)]">{t('Archive')}</span>
        )}
      </div>
    ))
  }
  return (
    <section aria-label={t('tasks.linked')} className="space-y-3">
      {error && (
        <p role="alert" className="text-xs text-[var(--destructive)]">
          {t('tasks.saveError')}
        </p>
      )}
      {linked.length > 0 && (
        <div className="space-y-2">
          <h3 className="px-1 text-xs font-medium text-[var(--muted-foreground)]">
            {t('tasks.linked')}
          </h3>
          {rows(linked, true)}
        </div>
      )}
      {assigned.length > 0 && (
        <div className="space-y-2">
          <h3 className="px-1 text-xs font-medium text-[var(--muted-foreground)]">
            {t('tasks.workspace')}
          </h3>
          {rows(assigned, false)}
        </div>
      )}
      <Link
        href="/kanban"
        className="inline-block text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      >
        {t('tasks.openBoard')}
      </Link>
    </section>
  )
}

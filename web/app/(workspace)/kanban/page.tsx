'use client'

import { useEffect, useRef, useState } from 'react'
import {
  Archive,
  ArrowLeft,
  ArrowRight,
  Check,
  ClipboardList,
  Plus,
  RotateCcw,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import SpaceSectionHeader from '@/components/space/SpaceSectionHeader'

import {
  createTaskCard,
  getTaskBoard,
  updateTaskCard,
  type TaskBoard,
  type TaskCard,
  type TaskStatus,
} from '@/lib/task-board-api'

const columns: { id: TaskStatus; title: string; hint: string; tone: string }[] = [
  { id: 'todo', title: 'kanban.todo', hint: 'kanban.todoHint', tone: 'var(--info)' },
  { id: 'doing', title: 'kanban.doing', hint: 'kanban.doingHint', tone: 'var(--warning)' },
  { id: 'done', title: 'kanban.done', hint: 'kanban.doneHint', tone: 'var(--success)' },
]

export default function KanbanPage() {
  const { t } = useTranslation()
  const [board, setBoard] = useState<TaskBoard | null>(null)
  const [title, setTitle] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftNote, setDraftNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragged, setDragged] = useState<string | null>(null)

  const pending = useRef(false)
  const [showArchived, setShowArchived] = useState(false)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getTaskBoard(controller.signal)
      .then(result => {
        if (!controller.signal.aborted) setBoard(result)
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('kanban.loadError')
      })
    return () => controller.abort()
  }, [reload])

  async function act(operation: () => Promise<TaskBoard>, onSuccess?: () => void) {
    if (pending.current || !board) return
    pending.current = true
    setBusy(true)
    setError('')
    try {
      setBoard(await operation())
      onSuccess?.()
    } catch {
      setError('kanban.saveError')
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  function startEdit(card: TaskCard) {
    setEditing(card.id)
    setDraftTitle(card.title)
    setDraftNote(card.note)
  }

  const active = board?.cards.filter(card => !card.archived) ?? []
  const visible = board?.cards.filter(card => card.archived === showArchived) ?? []
  const count = (status: TaskStatus) => visible.filter(card => card.status === status).length

  return (
    <div className="h-full overflow-y-auto bg-[var(--background)] [scrollbar-gutter:stable]">
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8 pb-12 font-sans text-[var(--foreground)]">
        <SpaceSectionHeader
          icon={ClipboardList}
          title={t('Task Board')}
          description={t('kanban.intro')}
          action={
            <button
              type="button"
              aria-pressed={showArchived}
              disabled={busy}
              onClick={() => {
                setShowArchived(value => !value)
                setEditing(null)
              }}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
            >
              {t(showArchived ? 'kanban.showActive' : 'kanban.showArchived')}
            </button>
          }
          meta={
            <span className="rounded-full bg-[var(--muted)] px-2.5 py-1 font-sans text-xs font-medium text-[var(--muted-foreground)]">
              {active.filter(card => card.status === 'doing').length} {t('kanban.working')}
            </span>
          }
        />

        <form
          className="mb-7 flex gap-2 rounded-2xl bg-[var(--card)] p-2 shadow-sm ring-1 ring-[var(--border)]"
          onSubmit={event => {
            event.preventDefault()
            if (title.trim())
              void act(
                () => createTaskCard(title),
                () => {
                  setTitle('')
                  setShowArchived(false)
                }
              )
          }}
        >
          <input
            disabled={!board || busy}
            aria-label={t('kanban.newTask')}
            className="min-w-0 flex-1 bg-transparent px-3 py-2 outline-none placeholder:text-[var(--muted-foreground)]"
            placeholder={t('kanban.placeholder')}
            maxLength={160}
            value={title}
            onChange={event => setTitle(event.target.value)}
          />
          <button
            disabled={busy || !board || !title.trim()}
            className="flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 font-semibold text-[var(--primary-foreground)] transition hover:opacity-90 disabled:opacity-40"
            type="submit"
          >
            <Plus size={18} /> {t('kanban.add')}
          </button>
        </form>
        {!board && !error && (
          <p role="status" className="mb-5 text-sm text-[var(--muted-foreground)]">
            {t('kanban.loading')}
          </p>
        )}
        {error && (
          <p
            role="alert"
            className="mb-5 rounded-xl bg-[var(--secondary)] p-3 text-sm text-[var(--destructive)]"
          >
            {t(error)}
            {!board && (
              <button
                type="button"
                className="ml-3 underline"
                onClick={() => {
                  setError('')
                  setReload(value => value + 1)
                }}
              >
                {t('kanban.retry')}
              </button>
            )}
          </p>
        )}

        <div aria-busy={busy || !board} className="grid gap-5 lg:grid-cols-3">
          {columns.map((column, index) => (
            <section
              key={column.id}
              aria-label={t(column.title)}
              onDragOver={event => event.preventDefault()}
              onDrop={event => {
                event.preventDefault()
                if (dragged && !showArchived)
                  void act(() => updateTaskCard(dragged, { status: column.id }))
                setDragged(null)
              }}
              className="min-h-[22rem] rounded-2xl border border-[var(--border)] bg-[var(--secondary)] p-4"
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: column.tone }}
                  />
                  <div>
                    <h2 className="font-semibold">{t(column.title)}</h2>
                    <p className="text-xs text-[var(--muted-foreground)]">{t(column.hint)}</p>
                  </div>
                </div>
                <span className="rounded-full bg-[var(--card)] px-2.5 py-1 text-xs font-bold text-[var(--muted-foreground)]">
                  {count(column.id)}
                </span>
              </div>
              <div className="space-y-3">
                {visible
                  .filter(card => card.status === column.id)
                  .map(card => (
                    <article
                      key={card.id}
                      draggable={!busy && !showArchived && editing !== card.id}
                      onDragStart={event => {
                        event.dataTransfer.setData('text/plain', card.id)
                        event.dataTransfer.effectAllowed = 'move'
                        setDragged(card.id)
                      }}
                      onDragEnd={() => setDragged(null)}
                      className="rounded-xl bg-[var(--card)] p-4 shadow-sm ring-1 ring-[var(--border)]"
                    >
                      {editing === card.id ? (
                        <form
                          onSubmit={event => {
                            event.preventDefault()
                            if (draftTitle.trim())
                              void act(
                                () =>
                                  updateTaskCard(card.id, { title: draftTitle, note: draftNote }),
                                () => setEditing(null)
                              )
                          }}
                        >
                          <input
                            aria-label={t('kanban.taskTitle')}
                            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1 font-semibold text-[var(--foreground)]"
                            maxLength={160}
                            value={draftTitle}
                            onChange={event => setDraftTitle(event.target.value)}
                          />
                          <textarea
                            aria-label={t('kanban.taskNote')}
                            className="mt-2 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm text-[var(--foreground)]"
                            placeholder={t('kanban.notePlaceholder')}
                            rows={3}
                            maxLength={2000}
                            value={draftNote}
                            onChange={event => setDraftNote(event.target.value)}
                          />
                          <div className="mt-2 flex gap-2">
                            <button
                              disabled={busy || !draftTitle.trim()}
                              className="flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-xs font-semibold text-[var(--primary-foreground)] disabled:opacity-40"
                              type="submit"
                            >
                              <Check size={14} /> {t('kanban.save')}
                            </button>
                            <button
                              className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-[var(--muted-foreground)]"
                              type="button"
                              onClick={() => setEditing(null)}
                            >
                              <X size={14} /> {t('kanban.cancel')}
                            </button>
                          </div>
                        </form>
                      ) : (
                        <>
                          <button
                            type="button"
                            disabled={busy}
                            className="w-full text-left"
                            onClick={() => startEdit(card)}
                          >
                            <strong className="break-words text-sm leading-6">{card.title}</strong>
                            {card.note && (
                              <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-[var(--muted-foreground)]">
                                {card.note}
                              </p>
                            )}
                          </button>
                          <div className="mt-4 flex items-center justify-between border-t border-[var(--border)] pt-3">
                            <div className="flex gap-1">
                              {!showArchived && index > 0 && (
                                <button
                                  disabled={busy}
                                  aria-label={`${card.title}: ${t('kanban.moveTo')} ${t(columns[index - 1].title)}`}
                                  title={t('kanban.back')}
                                  className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
                                  onClick={() =>
                                    void act(() =>
                                      updateTaskCard(card.id, { status: columns[index - 1].id })
                                    )
                                  }
                                >
                                  <ArrowLeft size={16} />
                                </button>
                              )}
                              {!showArchived && index < 2 && (
                                <button
                                  disabled={busy}
                                  aria-label={`${card.title}: ${t('kanban.moveTo')} ${t(columns[index + 1].title)}`}
                                  title={t('kanban.forward')}
                                  className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
                                  onClick={() =>
                                    void act(() =>
                                      updateTaskCard(card.id, { status: columns[index + 1].id })
                                    )
                                  }
                                >
                                  <ArrowRight size={16} />
                                </button>
                              )}
                            </div>
                            <button
                              disabled={busy}
                              aria-label={`${card.title}: ${t(card.archived ? 'kanban.restore' : 'kanban.archive')}`}
                              title={t(card.archived ? 'kanban.restore' : 'kanban.archive')}
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
                              onClick={() =>
                                void act(() =>
                                  updateTaskCard(card.id, { archived: !card.archived })
                                )
                              }
                            >
                              {card.archived ? <RotateCcw size={15} /> : <Archive size={15} />}
                            </button>
                          </div>
                        </>
                      )}
                    </article>
                  ))}
                {board && count(column.id) === 0 && (
                  <p className="rounded-xl border border-dashed border-[var(--border)] px-4 py-10 text-center text-sm text-[var(--muted-foreground)]">
                    {t(showArchived ? 'kanban.emptyArchive' : 'kanban.empty')}
                  </p>
                )}
              </div>
            </section>
          ))}
        </div>
        <p className="mt-6 text-xs text-[var(--muted-foreground)]">{t('kanban.footer')}</p>
      </main>
    </div>
  )
}

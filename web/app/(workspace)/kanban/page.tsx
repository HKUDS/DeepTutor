'use client'

import { FeaturePage, pageGridClass } from '@/components/layout/FeaturePage'
import { useRef, useState } from 'react'
import {
  Archive,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  CircleCheck,
  CircleDashed,
  CircleDot,
  Folder,
  Plus,
  RotateCcw,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import SpaceSectionHeader from '@/components/space/SpaceSectionHeader'
import Tooltip from '@/shared/ui/Tooltip'
import TaskColorPicker from '@/components/tasks/TaskColorPicker'

import {
  createTaskCard,
  updateTaskColors,
  DEFAULT_TASK_COLORS,
  updateTaskCard,
  type TaskBoard,
  type TaskCard,
  type TaskStatus,
} from '@/lib/task-board-api'

import { useTaskBoard, refreshTaskBoard } from '@/lib/task-board-store'
import { useChatWorkspaces } from '@/hooks/useChatWorkspaces'

const columns = [
  { id: 'todo', title: 'kanban.todo', hint: 'kanban.todoHint', icon: CircleDashed },
  { id: 'doing', title: 'kanban.doing', hint: 'kanban.doingHint', icon: CircleDot },
  { id: 'done', title: 'kanban.done', hint: 'kanban.doneHint', icon: CircleCheck },
] as const

export default function KanbanPage() {
  const { t } = useTranslation()
  const { board, error: loadError } = useTaskBoard()
  const { workspaces } = useChatWorkspaces()
  const [title, setTitle] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftNote, setDraftNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragged, setDragged] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<TaskStatus | null>(null)

  const pending = useRef(false)
  const [showArchived, setShowArchived] = useState(false)
  async function act(operation: () => Promise<TaskBoard>, onSuccess?: () => void) {
    if (pending.current || !board) return
    pending.current = true
    setBusy(true)
    setError('')
    try {
      await operation()
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
    <FeaturePage>
        <SpaceSectionHeader
          title={t('Task Board')}
          description={t('kanban.intro')}
          action={
            <div className="flex items-center gap-1">
              <TaskColorPicker
                colors={board?.colors ?? DEFAULT_TASK_COLORS}
                disabled={!board}
                busy={busy}
                error={error ? t(error) : undefined}
                onSave={(colors, onSuccess) => void act(() => updateTaskColors(colors), onSuccess)}
              />
              <button
                type="button"
                aria-pressed={showArchived}
                disabled={busy}
                onClick={() => {
                  setShowArchived(value => !value)
                  setEditing(null)
                }}
                className={`inline-flex h-9 items-center gap-2 rounded-lg px-3 text-[13px] font-medium transition-colors disabled:opacity-40 ${showArchived ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'}`}
              >
                <Archive size={15} strokeWidth={1.7} />
                {t(showArchived ? 'kanban.showActive' : 'kanban.showArchived')}
              </button>
            </div>
          }
          meta={
            <span className="rounded-md bg-muted/65 px-2 py-0.5 font-sans text-[11px] font-medium text-muted-foreground">
              {active.filter(card => card.status === 'doing').length} {t('kanban.working')}
            </span>
          }
        />

        <form
          className="mb-6 flex items-center gap-2 rounded-xl border border-border/80 bg-card p-1.5 transition-[border-color,box-shadow] focus-within:border-primary/40 focus-within:ring-[3px] focus-within:ring-primary/5"
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
            className="min-w-0 flex-1 bg-transparent px-3 py-2 text-[13px] outline-none placeholder:text-muted-foreground/75 focus-visible:outline-none"
            placeholder={t('kanban.placeholder')}
            maxLength={160}
            value={title}
            onChange={event => setTitle(event.target.value)}
          />
          <button
            disabled={busy || !board || !title.trim()}
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-[13px] font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-60"
            type="submit"
          >
            <Plus size={15} strokeWidth={1.8} /> {t('kanban.add')}
          </button>
        </form>
        {!board && !error && !loadError && (
          <p role="status" className="mb-5 text-sm text-muted-foreground">
            {t('kanban.loading')}
          </p>
        )}
        {(error || loadError) && (
          <p role="alert" className="mb-5 rounded-xl bg-secondary p-3 text-sm text-destructive">
            {t(error || 'kanban.loadError')}
            {!board && (
              <button
                type="button"
                className="ml-3 underline"
                onClick={() => {
                  setError('')
                  void refreshTaskBoard()
                }}
              >
                {t('kanban.retry')}
              </button>
            )}
          </p>
        )}

        <div aria-busy={busy || !board} className={pageGridClass('board')}>
          {columns.map((column, index) => (
            <section
              key={column.id}
              aria-label={t(column.title)}
              onDragOver={event => {
                event.preventDefault()
                if (dragged && !showArchived) setDropTarget(column.id)
              }}
              onDragLeave={event => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null))
                  setDropTarget(null)
              }}
              onDrop={event => {
                event.preventDefault()
                if (dragged && !showArchived)
                  void act(() => updateTaskCard(dragged, { status: column.id }))
                setDragged(null)
                setDropTarget(null)
              }}
              className={`min-h-[12rem] rounded-2xl border p-3 transition-colors sm:p-3.5 lg:min-h-[24rem] ${dropTarget === column.id ? 'border-primary/35 bg-primary/5 ring-2 ring-primary/10' : 'border-border/45 bg-secondary/65'}`}
            >
              <div className="mb-3 flex items-center justify-between px-1 py-1.5">
                <div className="flex items-start gap-2.5">
                  <span
                    className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                    style={{
                      backgroundColor: board?.colors[column.id] ?? DEFAULT_TASK_COLORS[column.id],
                    }}
                  />
                  <div>
                    <h2 className="text-[13px] font-semibold leading-5">{t(column.title)}</h2>
                    <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                      {t(column.hint)}
                    </p>
                  </div>
                </div>
                <span className="self-start px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
                  {count(column.id)}
                </span>
              </div>
              <div className="space-y-2.5">
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
                      onDragEnd={() => {
                        setDragged(null)
                        setDropTarget(null)
                      }}
                      className={`group/kanban-card rounded-xl border border-border/75 bg-card px-3.5 py-3 shadow-[0_1px_2px_rgba(0,0,0,0.025)] transition-[border-color,box-shadow,opacity] hover:border-border hover:shadow-[0_2px_8px_rgba(0,0,0,0.045)] ${dragged === card.id ? 'opacity-45' : ''}`}
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
                            className="w-full rounded-lg border border-border bg-background px-2.5 py-2 text-[13px] font-medium text-foreground focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/10"
                            maxLength={160}
                            value={draftTitle}
                            onChange={event => setDraftTitle(event.target.value)}
                          />
                          <textarea
                            aria-label={t('kanban.taskNote')}
                            className="mt-2 w-full resize-y rounded-lg border border-border bg-background px-2.5 py-2 text-xs leading-5 text-foreground focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/10"
                            placeholder={t('kanban.notePlaceholder')}
                            rows={3}
                            maxLength={2000}
                            value={draftNote}
                            onChange={event => setDraftNote(event.target.value)}
                          />
                          <div className="mt-2 flex gap-2">
                            <button
                              disabled={busy || !draftTitle.trim()}
                              className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-40"
                              type="submit"
                            >
                              <Check size={14} /> {t('kanban.save')}
                            </button>
                            <button
                              className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-muted-foreground"
                              type="button"
                              onClick={() => setEditing(null)}
                            >
                              <X size={14} /> {t('kanban.cancel')}
                            </button>
                          </div>
                        </form>
                      ) : (
                        <div className="relative">
                          <button
                            type="button"
                            aria-label={card.title}
                            disabled={busy}
                            className="block w-full text-left"
                            onClick={() => startEdit(card)}
                          >
                            <strong className="block break-words text-[13px] font-medium leading-6">
                              {card.title}
                            </strong>
                            {card.note && (
                              <p className="mt-1.5 whitespace-pre-wrap break-words text-xs leading-5 text-muted-foreground">
                                {card.note}
                              </p>
                            )}
                          </button>
                          <label className="relative mt-3 inline-flex max-w-full items-center gap-1.5 rounded-md bg-muted/50 px-2 py-1 text-[11px] leading-4 text-muted-foreground transition-colors hover:bg-muted focus-within:ring-2 focus-within:ring-ring/40">
                            <Folder aria-hidden size={11} strokeWidth={1.7} className="shrink-0" />
                            <span className="truncate">
                              {card.workspace_id === null
                                ? t('tasks.unassigned')
                                : card.workspace_id === ''
                                  ? t('General workspace')
                                  : (workspaces.find(row => row.workspace_id === card.workspace_id)
                                      ?.display_name ?? t('tasks.assign'))}
                            </span>
                            <ChevronDown
                              aria-hidden
                              size={11}
                              strokeWidth={1.7}
                              className="shrink-0 opacity-60"
                            />
                            <select
                              aria-label={`${card.title}: ${t('tasks.assign')}`}
                              disabled={busy}
                              value={card.workspace_id ?? '__unassigned__'}
                              onChange={event =>
                                void act(() =>
                                  updateTaskCard(card.id, {
                                    workspace_id:
                                      event.target.value === '__unassigned__'
                                        ? null
                                        : event.target.value,
                                  })
                                )
                              }
                              className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-default"
                            >
                              <option value="__unassigned__">{t('tasks.unassigned')}</option>
                              <option value="">{t('General workspace')}</option>
                              {workspaces
                                .filter(row => row.kind === 'workspace')
                                .map(row => (
                                  <option
                                    key={row.workspace_id}
                                    value={row.workspace_id}
                                    disabled={row.archived || row.status !== 'ready'}
                                  >
                                    {row.display_name}
                                  </option>
                                ))}
                            </select>
                          </label>
                          <div className="pointer-events-none absolute -right-0.5 -top-0.5 flex items-center gap-0.5 rounded-r-md bg-gradient-to-l from-popover from-80% to-transparent pl-4 opacity-0 transition-opacity duration-150 group-hover/kanban-card:pointer-events-auto group-hover/kanban-card:opacity-100 group-has-[:focus-visible]/kanban-card:pointer-events-auto group-has-[:focus-visible]/kanban-card:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100">
                            {!showArchived && index > 0 && (
                              <Tooltip label={t('kanban.back')}>
                                <button
                                  disabled={busy}
                                  aria-label={`${card.title}: ${t('kanban.moveTo')} ${t(columns[index - 1].title)}`}
                                  className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent"
                                  onClick={() =>
                                    void act(() =>
                                      updateTaskCard(card.id, { status: columns[index - 1].id })
                                    )
                                  }
                                >
                                  <ArrowLeft size={16} />
                                </button>
                              </Tooltip>
                            )}
                            {!showArchived && index < 2 && (
                              <Tooltip label={t('kanban.forward')}>
                                <button
                                  disabled={busy}
                                  aria-label={`${card.title}: ${t('kanban.moveTo')} ${t(columns[index + 1].title)}`}
                                  className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent"
                                  onClick={() =>
                                    void act(() =>
                                      updateTaskCard(card.id, { status: columns[index + 1].id })
                                    )
                                  }
                                >
                                  <ArrowRight size={16} />
                                </button>
                              </Tooltip>
                            )}
                            <Tooltip label={t(card.archived ? 'kanban.restore' : 'kanban.archive')}>
                              <button
                                disabled={busy}
                                aria-label={`${card.title}: ${t(card.archived ? 'kanban.restore' : 'kanban.archive')}`}
                                className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent"
                                onClick={() =>
                                  void act(() =>
                                    updateTaskCard(card.id, { archived: !card.archived })
                                  )
                                }
                              >
                                {card.archived ? <RotateCcw size={15} /> : <Archive size={15} />}
                              </button>
                            </Tooltip>
                          </div>
                        </div>
                      )}
                    </article>
                  ))}
                {board && count(column.id) === 0 && (
                  <div className="flex min-h-28 flex-col items-center justify-center gap-2.5 rounded-xl border border-dashed border-border/65 px-4 py-6 text-center">
                    <column.icon
                      aria-hidden
                      size={20}
                      strokeWidth={1.3}
                      className="text-muted-foreground/40"
                    />
                    <p className="text-[11px] text-muted-foreground">
                      {t(showArchived ? 'kanban.emptyArchive' : 'kanban.empty')}
                    </p>
                  </div>
                )}
              </div>
            </section>
          ))}
        </div>
        <p className="mt-5 px-1 text-[11px] leading-5 text-muted-foreground">
          {t('kanban.footer')}
        </p>
    </FeaturePage>
  )
}

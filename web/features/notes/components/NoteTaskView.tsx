'use client'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Table2, Columns3, List, Search, Plus } from 'lucide-react'
import { useActiveWorkspaceId } from '@/hooks/useActiveWorkspaceId'
import {
  getTaskBoard,
  createTaskCard,
  updateTaskCard,
  subscribeTaskBoardChanges,
  type TaskCard,
  type TaskStatus,
} from '@/lib/task-board-api'
const statuses: TaskStatus[] = ['todo', 'doing', 'done']
const labels = { todo: 'To do', doing: 'In progress', done: 'Done' }
export default function NoteTaskView({
  view,
  onViewChange,
}: {
  view: string
  onViewChange: (view: string) => void
}) {
  const { t } = useTranslation()
  const workspaceId = useActiveWorkspaceId()
  const [cards, setCards] = useState<TaskCard[]>([])
  const [query, setQuery] = useState('')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void getTaskBoard(controller.signal, workspaceId || '')
      .then(b => setCards(b.cards))
      .catch(e => {
        if (!controller.signal.aborted) setError(String(e))
      })
    const off = subscribeTaskBoardChanges((b, scope) => {
      if (scope === (workspaceId || '')) setCards(b.cards)
    })
    return () => {
      controller.abort()
      off()
    }
  }, [workspaceId])
  const visible = cards.filter(
    c => !c.archived && c.title.toLowerCase().includes(query.toLowerCase())
  )
  const update = async (card: TaskCard, changes: Partial<TaskCard>) => {
    setBusy(true)
    setError('')
    try {
      await updateTaskCard(card.id, changes)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }
  const status = (c: TaskCard) => (
    <select
      disabled={busy}
      aria-label={`${t('Status')}: ${c.title}`}
      value={c.status}
      onChange={e => void update(c, { status: e.target.value as TaskStatus })}
    >
      {statuses.map(s => (
        <option key={s} value={s}>
          {t(labels[s])}
        </option>
      ))}
    </select>
  )
  return (
    <section>
      <header>
        <strong>{t('Workspace tasks')}</strong>
        <div role="tablist" aria-label={t('Task view')}>
          {(
            [
              ['table', Table2, 'Table'],
              ['board', Columns3, 'Board'],
              ['list', List, 'List'],
            ] as const
          ).map(([key, Icon, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={view === key}
              onClick={() => onViewChange(key)}
            >
              <Icon size={14} />
              {t(label)}
            </button>
          ))}
        </div>
      </header>
      <label className="dt-note-view-search">
        <Search size={14} />
        <input
          aria-label={t('Search tasks')}
          placeholder={t('Search tasks')}
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
      </label>
      {view === 'board' ? (
        <div className="dt-note-task-columns">
          {statuses.map(s => (
            <div key={s}>
              <h4>
                {t(labels[s])}
                <span>{visible.filter(c => c.status === s).length}</span>
              </h4>
              {visible
                .filter(c => c.status === s)
                .map(c => (
                  <article key={c.id}>
                    <p>{c.title}</p>
                    {status(c)}
                    {c.due_date && <small>{c.due_date}</small>}
                  </article>
                ))}
            </div>
          ))}
        </div>
      ) : view === 'list' ? (
        <div className="dt-note-task-list">
          {visible.map(c => (
            <label key={c.id}>
              <input
                type="checkbox"
                disabled={busy}
                checked={c.status === 'done'}
                onChange={e => void update(c, { status: e.target.checked ? 'done' : 'todo' })}
              />
              <span>{c.title}</span>
              <small>{c.due_date}</small>
            </label>
          ))}
        </div>
      ) : (
        <div className="dt-note-table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t('Task')}</th>
                <th>{t('Status')}</th>
                <th>{t('Due date')}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map(c => (
                <tr key={c.id}>
                  <td>{c.title}</td>
                  <td>{status(c)}</td>
                  <td>
                    <input
                      type="date"
                      disabled={busy}
                      aria-label={`${t('Due date')}: ${c.title}`}
                      value={c.due_date || ''}
                      onChange={e => void update(c, { due_date: e.target.value || null })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!visible.length && <p className="dt-note-hint">{t('No tasks yet')}</p>}
      <form
        className="dt-note-new-task"
        onSubmit={async e => {
          e.preventDefault()
          if (!title.trim()) return
          setBusy(true)
          setError('')
          try {
            await createTaskCard(title.trim())
            setTitle('')
          } catch (e) {
            setError(String(e))
          } finally {
            setBusy(false)
          }
        }}
      >
        <Plus size={15} />
        <input
          aria-label={t('New task')}
          placeholder={t('New task')}
          value={title}
          onChange={e => setTitle(e.target.value)}
        />
        <button disabled={busy || !title.trim()}>{t('Add')}</button>
      </form>
      {error && <p role="alert">{error}</p>}
    </section>
  )
}

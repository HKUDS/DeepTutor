'use client'

import { useRef, useState, type RefObject } from 'react'
import { Check, Palette, RotateCcw, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useOutsideClick } from '@/hooks/use-outside-click'
import { useModalDialog } from '@/hooks/useModalDialog'
import { DEFAULT_TASK_COLORS, type TaskColors, type TaskStatus } from '@/lib/task-board-api'

const statuses: TaskStatus[] = ['todo', 'doing', 'done']
const swatches = [
  '#2563eb',
  '#4f46e5',
  '#8b5cf6',
  '#db2777',
  '#e11d48',
  '#ea580c',
  '#0284c7',
  '#0d9488',
  '#15803d',
  '#65a30d',
  '#a16207',
  '#64748b',
]

type SaveColors = (colors: TaskColors, onSuccess: () => void) => void

export default function TaskColorPicker({
  colors,
  disabled,
  busy,
  error,
  onSave,
}: {
  colors: TaskColors
  disabled: boolean
  busy: boolean
  error?: string
  onSave: SaveColors
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  useOutsideClick(rootRef, open && !busy, () => setOpen(false))

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled || busy}
        aria-label={t('tasks.colors')}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen(value => !value)}
        className={`dt-page-action inline-flex h-9 items-center gap-2 rounded-lg px-3 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-40 ${open ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'}`}
      >
        <Palette size={15} strokeWidth={1.7} />
        {t('tasks.colors')}
        <span aria-hidden className="ml-1 flex items-center -space-x-1">
          {statuses.map(status => (
            <span
              key={status}
              className="h-2.5 w-2.5 rounded-full ring-2 ring-background"
              style={{ backgroundColor: colors[status] }}
            />
          ))}
        </span>
      </button>
      {open && (
        <ColorPanel
          colors={colors}
          busy={busy}
          error={error}
          onSave={onSave}
          onClose={() => setOpen(false)}
          triggerRef={triggerRef}
        />
      )}
    </div>
  )
}

function ColorPanel({
  colors,
  busy,
  error,
  onSave,
  onClose,
  triggerRef,
}: {
  colors: TaskColors
  busy: boolean
  error?: string
  onSave: SaveColors
  onClose: () => void
  triggerRef: RefObject<HTMLButtonElement | null>
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(colors)
  const [status, setStatus] = useState<TaskStatus>('todo')
  const [hex, setHex] = useState(colors.todo)
  const dialogRef = useModalDialog(onClose, busy, triggerRef)
  const validHex = /^#[0-9a-f]{6}$/i.test(hex)
  const changed = statuses.some(key => draft[key].toLowerCase() !== colors[key].toLowerCase())

  function choose(color: string) {
    setHex(color)
    setDraft(value => ({ ...value, [status]: color }))
  }

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-label={t('tasks.colors')}
      style={{ boxShadow: 'var(--shadow-raised)' }}
      className="absolute left-0 top-full z-50 mt-2 w-[min(320px,calc(100vw-48px))] overflow-hidden rounded-2xl border border-border/70 bg-popover text-foreground backdrop-blur-xl md:left-auto md:right-0"
    >
      <div className="flex items-center justify-between px-4 pb-3 pt-4">
        <h2 className="text-[13px] font-semibold">{t('tasks.colors')}</h2>
        <button
          type="button"
          aria-label={t('Close')}
          disabled={busy}
          onClick={onClose}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        >
          <X size={14} strokeWidth={1.7} />
        </button>
      </div>
      <div className="px-4 pb-4">
        <div
          role="group"
          aria-label={t('tasks.status')}
          className="flex gap-1 rounded-xl bg-muted/65 p-1"
        >
          {statuses.map(key => (
            <button
              key={key}
              type="button"
              aria-pressed={status === key}
              data-modal-initial-focus={status === key || undefined}
              disabled={busy}
              onClick={() => {
                setStatus(key)
                setHex(draft[key])
              }}
              className={`flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg px-1 py-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 ${status === key ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: draft[key] }}
              />
              {t(`kanban.${key}`)}
            </button>
          ))}
        </div>
        <div role="group" aria-label={t('Choose color')} className="mt-4 grid grid-cols-6 gap-2">
          {swatches.map(color => {
            const selected = draft[status].toLowerCase() === color
            return (
              <button
                key={color}
                type="button"
                aria-label={`${t('Choose color')}: ${color}`}
                aria-pressed={selected}
                disabled={busy}
                onClick={() => choose(color)}
                className="group flex h-10 items-center justify-center rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-40"
              >
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full text-white transition-transform duration-150 group-hover:scale-110 ${selected ? 'ring-2 ring-foreground/65 ring-offset-[3px] ring-offset-popover' : ''}`}
                  style={{ backgroundColor: color }}
                >
                  {selected && <Check size={13} strokeWidth={2.3} />}
                </span>
              </button>
            )
          })}
        </div>
        <div className="mt-4 flex items-center justify-between gap-3 rounded-xl bg-muted/45 px-3 py-2">
          <span className="text-xs text-muted-foreground">{t('Custom')}</span>
          <span className="flex items-center gap-2">
            <span className="relative flex h-6 w-6 items-center justify-center rounded-md focus-within:ring-2 focus-within:ring-ring/40">
              <span
                aria-hidden
                className="h-3.5 w-3.5 rounded-full shadow-[inset_0_0_0_1px_rgba(0,0,0,0.08)]"
                style={{ backgroundColor: draft[status] }}
              />
              <input
                type="color"
                aria-label={`${t(`kanban.${status}`)}: ${t('Choose color')}`}
                disabled={busy}
                value={draft[status]}
                onChange={event => choose(event.target.value)}
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
              />
            </span>
            <input
              aria-label={`${t(`kanban.${status}`)}: ${t('tasks.color')}`}
              aria-invalid={!validHex}
              value={hex.toUpperCase()}
              maxLength={7}
              spellCheck={false}
              disabled={busy}
              onChange={event => {
                const value = event.target.value
                setHex(value)
                if (/^#[0-9a-f]{6}$/i.test(value))
                  setDraft(current => ({ ...current, [status]: value }))
              }}
              className="w-[76px] rounded bg-transparent py-1 text-right font-mono text-xs uppercase tracking-wide outline-none focus-visible:ring-2 focus-visible:ring-ring/40 aria-[invalid=true]:text-destructive"
            />
          </span>
        </div>
        {error && (
          <p role="alert" className="mt-3 text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
      <div className="flex items-center justify-between border-t border-border/60 px-4 py-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setDraft({ ...DEFAULT_TASK_COLORS })
            setHex(DEFAULT_TASK_COLORS[status])
          }}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        >
          <RotateCcw size={12} strokeWidth={1.7} /> {t('Reset')}
        </button>
        <button
          type="button"
          disabled={busy || !validHex || !changed}
          onClick={() => onSave(draft, onClose)}
          className="rounded-lg bg-primary px-3.5 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-2 disabled:opacity-40"
        >
          {t('kanban.save')}
        </button>
      </div>
    </div>
  )
}

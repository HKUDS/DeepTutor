'use client'

import { useState, type CSSProperties, type FormEvent } from 'react'
import Link from 'next/link'
import {
  AlarmClock,
  Bell,
  BellOff,
  GripVertical,
  Check,
  CircleDashed,
  Footprints,
  MoreHorizontal,
  Plus,
  Repeat2,
  Trash2,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import type { TaskCard, TaskColors } from '@/lib/task-board-api'
import { LAYER_COLORS, type LayerId, type LayerToggles } from '../model/items'
import type { CalendarEntry } from '../transport/api'
import { MiniMonth } from './MiniMonth'
import { writeTaskDrag } from './task-drag'

export const CALENDAR_COLORS = [
  '#2f6fde',
  '#0f8b6c',
  '#d9730d',
  '#e03e3e',
  '#8a5cc2',
  '#c14c8a',
  '#2b8bb3',
  '#c29318',
  '#787774',
]

export function calendarName(calendar: CalendarEntry, t: (key: string) => string): string {
  return calendar.is_default && !calendar.name ? t('My calendar') : calendar.name
}

export function CalendarRail({
  cursor,
  range,
  weekStart,
  now,
  onPick,
  tasks,
  taskColors,
  calendars,
  onUpdateCalendar,
  onCreateCalendar,
  onDeleteCalendar,
  layers,
  onToggleLayer,
  notifications,
  onEnableNotifications,
}: {
  cursor: Date
  range: [string, string]
  weekStart: number
  now: Date
  onPick: (day: Date) => void
  tasks: TaskCard[] | null
  taskColors: TaskColors
  calendars: CalendarEntry[]
  onUpdateCalendar: (
    calendar: CalendarEntry,
    changes: Partial<Pick<CalendarEntry, 'name' | 'color' | 'visible'>>
  ) => void
  onCreateCalendar: (name: string, color: string) => void
  onDeleteCalendar: (calendar: CalendarEntry) => void
  layers: LayerToggles
  onToggleLayer: (layer: LayerId) => void
  notifications: NotificationPermission | 'unsupported'
  onEnableNotifications: () => void
}) {
  const { t } = useTranslation()
  const unscheduled = (tasks ?? []).filter(
    card => !card.archived && card.status !== 'done' && !card.due_date
  )
  return (
    <aside className="dt-cal-rail" aria-label={t('Calendar sidebar')}>
      <MiniMonth cursor={cursor} range={range} weekStart={weekStart} today={now} onPick={onPick} />

      <section className="dt-cal-rail-section">
        <div className="dt-cal-rail-label">
          <span>
            {t('Unscheduled tasks')}
            {unscheduled.length > 0 && <span className="dt-cal-rail-count">{unscheduled.length}</span>}
          </span>
          <Link href="/kanban" prefetch={false} className="dt-cal-rail-link">
            {t('Task Board')}
          </Link>
        </div>
        {tasks === null ? null : unscheduled.length ? (
          <>
            <ul className="dt-cal-task-list">
              {unscheduled.map(card => (
                <li key={card.id}>
                  <div
                    draggable
                    className="dt-cal-task"
                    style={{ '--ev': taskColors[card.status] } as CSSProperties}
                    onDragStart={event => writeTaskDrag(event.dataTransfer, card.id)}
                  >
                    <CircleDashed aria-hidden size={13} strokeWidth={2} />
                    <span>{card.title}</span>
                    <GripVertical aria-hidden size={13} className="dt-cal-task-grip" />
                  </div>
                </li>
              ))}
            </ul>
            <p className="dt-cal-rail-hint">{t('Drag onto the calendar to schedule it.')}</p>
          </>
        ) : (
          <p className="dt-cal-rail-hint">{t('Every open task has a date.')}</p>
        )}
      </section>

      <section className="dt-cal-rail-section">
        <div className="dt-cal-rail-label">
          <span>{t('Calendars')}</span>
        </div>
        <ul className="dt-cal-calendar-list">
          {calendars.map(calendar => (
            <CalendarRow
              key={calendar.id}
              calendar={calendar}
              onUpdate={changes => onUpdateCalendar(calendar, changes)}
              onDelete={() => onDeleteCalendar(calendar)}
            />
          ))}
        </ul>
        <NewCalendar used={calendars.map(calendar => calendar.color)} onCreate={onCreateCalendar} />
      </section>

      <section className="dt-cal-rail-section">
        <div className="dt-cal-rail-label">
          <span>{t('From this workspace')}</span>
        </div>
        <ul className="dt-cal-calendar-list">
          <LayerRow
            id="tasks"
            label={t('Task due dates')}
            color={taskColors.todo}
            icon={CircleDashed}
            toggles={layers}
            onToggle={onToggleLayer}
          />
          <LayerRow
            id="reviews"
            label={t('Reviews coming due')}
            color={LAYER_COLORS.review}
            icon={Repeat2}
            toggles={layers}
            onToggle={onToggleLayer}
          />
          <LayerRow
            id="automations"
            label={t('Automations')}
            color={LAYER_COLORS.automation}
            icon={AlarmClock}
            toggles={layers}
            onToggle={onToggleLayer}
          />
          <LayerRow
            id="footprints"
            label={t('Learning footprints')}
            color="#787774"
            icon={Footprints}
            toggles={layers}
            onToggle={onToggleLayer}
          />
        </ul>
      </section>

      <footer className="dt-cal-rail-foot">
        {notifications === 'default' ? (
          <Tooltip label={t('Reminders work while DeepTutor is open.')}>
            <button type="button" className="dt-cal-rail-notify" onClick={onEnableNotifications}>
              <Bell aria-hidden size={14} strokeWidth={1.8} />
              {t('Turn on reminders')}
            </button>
          </Tooltip>
        ) : notifications === 'denied' ? (
          <p className="dt-cal-rail-hint">
            <BellOff aria-hidden size={13} strokeWidth={1.8} />
            {t('Notifications are blocked; reminders show inside DeepTutor.')}
          </p>
        ) : notifications === 'granted' ? (
          <p className="dt-cal-rail-hint">
            <Bell aria-hidden size={13} strokeWidth={1.8} />
            {t('Reminders work while DeepTutor is open.')}
          </p>
        ) : null}
      </footer>
    </aside>
  )
}

function Swatch({ color, checked }: { color: string; checked: boolean }) {
  return (
    <span
      aria-hidden
      className="dt-cal-swatch"
      data-checked={checked || undefined}
      style={{ '--ev': color } as CSSProperties}
    >
      {checked && <Check size={11} strokeWidth={3} />}
    </span>
  )
}

function LayerRow({
  id,
  label,
  color,
  icon: Icon,
  toggles,
  onToggle,
}: {
  id: LayerId
  label: string
  color: string
  icon: typeof Repeat2
  toggles: LayerToggles
  onToggle: (layer: LayerId) => void
}) {
  return (
    <li>
      <button
        type="button"
        role="checkbox"
        aria-checked={toggles[id]}
        className="dt-cal-calendar-row"
        onClick={() => onToggle(id)}
      >
        <Swatch color={color} checked={toggles[id]} />
        <span className="dt-cal-calendar-name">{label}</span>
        <Icon aria-hidden size={13} strokeWidth={1.8} className="dt-cal-layer-icon" />
      </button>
    </li>
  )
}

function CalendarRow({
  calendar,
  onUpdate,
  onDelete,
}: {
  calendar: CalendarEntry
  onUpdate: (changes: Partial<Pick<CalendarEntry, 'name' | 'color' | 'visible'>>) => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState('')
  const rootRef = useMenuPopover<HTMLLIElement>(open, setOpen)
  const label = calendarName(calendar, t)

  if (renaming)
    return (
      <li>
        <form
          className="dt-cal-calendar-form"
          onSubmit={event => {
            event.preventDefault()
            if (name.trim()) onUpdate({ name: name.trim() })
            setRenaming(false)
          }}
        >
          <Swatch color={calendar.color} checked={calendar.visible} />
          <input
            autoFocus
            aria-label={t('Calendar name')}
            value={name}
            maxLength={80}
            onChange={event => setName(event.target.value)}
            onBlur={() => setRenaming(false)}
            onKeyDown={event => {
              if (event.key === 'Escape') setRenaming(false)
            }}
          />
        </form>
      </li>
    )

  return (
    <li ref={rootRef} className="dt-cal-calendar-item">
      <button
        type="button"
        role="checkbox"
        aria-checked={calendar.visible}
        className="dt-cal-calendar-row"
        onClick={() => onUpdate({ visible: !calendar.visible })}
      >
        <Swatch color={calendar.color} checked={calendar.visible} />
        <span className="dt-cal-calendar-name">{label}</span>
      </button>
      <Tooltip label={t('Calendar options')} suppressed={open}>
        <button
          type="button"
          aria-label={t('Calendar options')}
          aria-haspopup="menu"
          aria-expanded={open}
          className="dt-cal-icon-button dt-cal-calendar-more"
          onClick={() => setOpen(value => !value)}
        >
          <MoreHorizontal size={14} strokeWidth={1.8} />
        </button>
      </Tooltip>
      {open && (
        <div role="menu" aria-label={label} className="dt-popover dt-cal-calendar-menu">
          <div className="dt-cal-color-grid" role="group" aria-label={t('Color')}>
            {CALENDAR_COLORS.map(color => (
              <button
                key={color}
                type="button"
                role="menuitemradio"
                aria-checked={color === calendar.color}
                aria-label={color}
                className="dt-cal-color"
                style={{ '--ev': color } as CSSProperties}
                onClick={() => {
                  onUpdate({ color })
                  setOpen(false)
                }}
              >
                {color === calendar.color && <Check size={11} strokeWidth={3} />}
              </button>
            ))}
          </div>
          <button
            type="button"
            role="menuitem"
            className="dt-menu-item"
            onClick={() => {
              setName(label)
              setRenaming(true)
              setOpen(false)
            }}
          >
            {t('Rename')}
          </button>
          {!calendar.is_default && (
            <button
              type="button"
              role="menuitem"
              className="dt-menu-item dt-cal-danger"
              onClick={() => {
                setOpen(false)
                onDelete()
              }}
            >
              <Trash2 size={14} strokeWidth={1.8} />
              {t('Delete calendar')}
            </button>
          )}
        </div>
      )}
    </li>
  )
}

function NewCalendar({
  used,
  onCreate,
}: {
  used: string[]
  onCreate: (name: string, color: string) => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const color = CALENDAR_COLORS.find(candidate => !used.includes(candidate)) ?? CALENDAR_COLORS[0]
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim()) onCreate(name.trim(), color)
    setName('')
    setEditing(false)
  }
  if (!editing)
    return (
      <button
        type="button"
        className="dt-cal-calendar-row dt-cal-add"
        onClick={() => setEditing(true)}
      >
        <Plus aria-hidden size={14} strokeWidth={1.8} />
        <span>{t('New calendar')}</span>
      </button>
    )
  return (
    <form className="dt-cal-calendar-form" onSubmit={submit}>
      <Swatch color={color} checked />
      <input
        autoFocus
        aria-label={t('Calendar name')}
        placeholder={t('Calendar name')}
        value={name}
        maxLength={80}
        onChange={event => setName(event.target.value)}
        onBlur={() => {
          if (!name.trim()) setEditing(false)
        }}
        onKeyDown={event => {
          if (event.key === 'Escape') setEditing(false)
        }}
      />
    </form>
  )
}

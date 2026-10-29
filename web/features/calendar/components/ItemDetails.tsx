'use client'

import { useState, type CSSProperties, type ReactNode } from 'react'
import Link from 'next/link'
import {
  AlarmClock,
  ArrowUpRight,
  Bell,
  CalendarClock,
  CalendarDays,
  CircleCheck,
  CircleDashed,
  Copy,
  Footprints,
  MapPin,
  MessageSquare,
  Pencil,
  Repeat,
  Repeat2,
  Sparkles,
  Text,
  Trash2,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import HeaderActionButton from '@/features/chat/components/HeaderActionButton'
import type { TaskCard } from '@/lib/task-board-api'
import { formatDate, formatTime, fromDateKey } from '../model/dates'
import { describeEvery, describeReminder, describeWhen } from '../model/describe'
import type { AutomationItem, CalendarItem, EventItem, ReviewItem, TaskItem } from '../model/items'
import { describeRule } from '../model/recurrence'
import type { CalendarEntry, FootprintDay } from '../transport/api'
import { footprintSummary } from './AgendaView'
import { calendarName } from './CalendarRail'
import { itemTitle } from './ItemChip'

function Row({ icon: Icon, children }: { icon: typeof Bell; children: ReactNode }) {
  return (
    <div className="dt-cal-detail-row">
      <Icon aria-hidden size={15} strokeWidth={1.7} />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function Head({
  color,
  title,
  sub,
  actions,
}: {
  color: string
  title: string
  sub?: ReactNode
  actions: ReactNode
}) {
  return (
    <>
      <div className="dt-cal-detail-actions">{actions}</div>
      <div className="dt-cal-detail-head">
        <span
          aria-hidden
          className="dt-cal-detail-square"
          style={{ '--ev': color } as CSSProperties}
        />
        <div className="min-w-0">
          <h3 className="dt-cal-detail-title">{title}</h3>
          {sub && <p className="dt-cal-detail-sub">{sub}</p>}
        </div>
      </div>
    </>
  )
}

export function EventDetails({
  item,
  calendars,
  task,
  onEdit,
  onDuplicate,
  onDelete,
  onClose,
  onCompleteTask,
}: {
  item: EventItem
  calendars: CalendarEntry[]
  task: TaskCard | undefined
  onEdit: () => void
  onDuplicate: () => void
  onDelete: () => void
  onClose: () => void
  onCompleteTask: (task: TaskCard) => void
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.language
  const { occurrence } = item
  const calendar = calendars.find(entry => entry.id === occurrence.calendar_id)
  return (
    <div className="dt-cal-detail">
      <Head
        color={item.color}
        title={itemTitle(item, t)}
        sub={describeWhen(item.start, item.end, item.allDay, locale)}
        actions={
          <>
            <HeaderActionButton icon={Pencil} label={t('Edit event')} onClick={onEdit} />
            <HeaderActionButton icon={Copy} label={t('Duplicate')} onClick={onDuplicate} />
            <HeaderActionButton icon={Trash2} label={t('Delete event')} onClick={onDelete} />
            <HeaderActionButton icon={X} label={t('Close')} onClick={onClose} />
          </>
        }
      />
      {occurrence.rrule && (
        <Row icon={Repeat}>{describeRule(occurrence.rrule, item.start, locale, t)}</Row>
      )}
      {occurrence.location && <Row icon={MapPin}>{occurrence.location}</Row>}
      {occurrence.task_id && (
        <Row icon={task?.status === 'done' ? CircleCheck : CircleDashed}>
          <div className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate">
              {task
                ? t('Time block for “{{task}}”', { task: task.title })
                : t('Time block for a task in another workspace')}
            </span>
            {task && task.status !== 'done' && (
              <button
                type="button"
                className="dt-cal-text-button"
                onClick={() => onCompleteTask(task)}
              >
                {t('Mark done')}
              </button>
            )}
          </div>
        </Row>
      )}
      {occurrence.notes && (
        <Row icon={Text}>
          <p className="dt-cal-detail-notes">{occurrence.notes}</p>
        </Row>
      )}
      {occurrence.reminders.length > 0 && (
        <Row icon={Bell}>
          {occurrence.reminders
            .map(minutes => describeReminder(minutes, occurrence.all_day, locale, t))
            .join(' · ')}
        </Row>
      )}
      {calendar && (
        <Row icon={CalendarDays}>
          <span className="flex items-center gap-2">
            <span
              aria-hidden
              className="dt-cal-chip-dot"
              style={{ '--ev': calendar.color } as CSSProperties}
            />
            {calendarName(calendar, t)}
          </span>
        </Row>
      )}
      {occurrence.source === 'dito' && <Row icon={Sparkles}>{t('Scheduled by Dito')}</Row>}
    </div>
  )
}

export function TaskDetails({
  item,
  onClose,
  onToggleDone,
  onClearDate,
  onSchedule,
  sessionIds = [],
}: {
  item: TaskItem
  onClose: () => void
  onToggleDone: () => void
  onClearDate: () => void
  sessionIds?: string[]
  onSchedule: () => void
}) {
  const { t, i18n } = useTranslation()
  const { card } = item
  const status = { todo: t('kanban.todo'), doing: t('kanban.doing'), done: t('kanban.done') }[
    card.status
  ]
  return (
    <div className="dt-cal-detail">
      <Head
        color={item.color}
        title={card.title}
        sub={`${status} · ${t('Due {{date}}', { date: formatDate(fromDateKey(card.due_date!), i18n.language, { month: 'short', day: 'numeric', weekday: 'short' }) })}`}
        actions={<HeaderActionButton icon={X} label={t('Close')} onClick={onClose} />}
      />
      {card.note && (
        <Row icon={Text}>
          <p className="dt-cal-detail-notes">{card.note}</p>
        </Row>
      )}
      {sessionIds.length > 0 && (
        <nav aria-label={t('Linked conversations')} className="dt-cal-detail-links">
          {sessionIds.map((id, index) => (
            <Link
              className="dt-cal-text-button mr-3"
              key={id}
              href={`/chat/${encodeURIComponent(id)}`}
            >
              {t('Conversation {{number}}', { number: index + 1 })}
            </Link>
          ))}
        </nav>
      )}
      <div className="dt-cal-detail-buttons">
        <button type="button" className="dt-cal-text-button" onClick={onToggleDone}>
          {card.status === 'done' ? t('Reopen') : t('Mark done')}
        </button>
        {card.status !== 'done' && (
          <button type="button" className="dt-cal-text-button" onClick={onSchedule}>
            {t('Block out time')}
          </button>
        )}
        <button type="button" className="dt-cal-text-button" onClick={onClearDate}>
          {t('Remove due date')}
        </button>
        <Link href="/kanban" prefetch={false} className="dt-cal-text-button">
          {t('Open board')}
          <ArrowUpRight aria-hidden size={12} />
        </Link>
      </div>
    </div>
  )
}

export function ReviewDetails({ item, onClose }: { item: ReviewItem; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const { day } = item
  return (
    <div className="dt-cal-detail">
      <Head
        color={item.color}
        title={itemTitle(item, t)}
        sub={formatDate(fromDateKey(day.date), i18n.language, {
          month: 'long',
          day: 'numeric',
          weekday: 'short',
        })}
        actions={<HeaderActionButton icon={X} label={t('Close')} onClick={onClose} />}
      />
      <ul className="dt-cal-detail-links">
        {day.paths.map(path => (
          <li key={path.id}>
            <Link href={`/learning/mastery/${encodeURIComponent(path.id)}`} prefetch={false}>
              <Repeat2 aria-hidden size={14} strokeWidth={1.8} />
              <span className="min-w-0 flex-1 truncate">{path.title}</span>
              <span className="dt-cal-count">{path.count}</span>
            </Link>
          </li>
        ))}
        {day.practice > 0 && (
          <li>
            <Link href="/learning/practice" prefetch={false}>
              <CircleCheck aria-hidden size={14} strokeWidth={1.8} />
              <span className="min-w-0 flex-1 truncate">{t('Question bank review')}</span>
              <span className="dt-cal-count">{day.practice}</span>
            </Link>
          </li>
        )}
      </ul>
    </div>
  )
}

export function AutomationDetails({
  item,
  onClose,
  onCancel,
}: {
  item: AutomationItem
  onClose: () => void
  onCancel: () => void
}) {
  const { t, i18n } = useTranslation()
  const [confirming, setConfirming] = useState(false)
  const { run } = item
  const schedule =
    run.kind === 'at'
      ? t('Once')
      : run.kind === 'every' && run.every_seconds
        ? describeEvery(run.every_seconds, t)
        : t('On the schedule {{expr}}', { expr: run.expr ?? '' })
  return (
    <div className="dt-cal-detail">
      <Head
        color={item.color}
        title={itemTitle(item, t)}
        sub={`${formatDate(item.start, i18n.language, { month: 'short', day: 'numeric', weekday: 'short' })} · ${formatTime(item.start, i18n.language)}`}
        actions={<HeaderActionButton icon={X} label={t('Close')} onClick={onClose} />}
      />
      <Row icon={CalendarClock}>{schedule}</Row>
      {run.message && run.message !== run.name && (
        <Row icon={AlarmClock}>
          <p className="dt-cal-detail-notes">{run.message}</p>
        </Row>
      )}
      <p className="dt-cal-detail-hint">
        {t('Dito set this up in a conversation and runs it at that time.')}
      </p>
      <div className="dt-cal-detail-buttons">
        {run.session_id && (
          <Link
            href={`/chat/${encodeURIComponent(run.session_id)}`}
            prefetch={false}
            className="dt-cal-text-button"
          >
            <MessageSquare aria-hidden size={13} />
            {t('Open conversation')}
          </Link>
        )}
        {confirming ? (
          <button type="button" className="dt-cal-text-button dt-cal-danger" onClick={onCancel}>
            {t('Stop it for good')}
          </button>
        ) : (
          <button type="button" className="dt-cal-text-button" onClick={() => setConfirming(true)}>
            {t('Stop this automation')}
          </button>
        )}
      </div>
    </div>
  )
}

export function FootprintDetails({ day, onClose }: { day: FootprintDay; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  return (
    <div className="dt-cal-detail">
      <Head
        color="#787774"
        title={t('Footprints')}
        sub={`${formatDate(fromDateKey(day.date), i18n.language, { month: 'long', day: 'numeric', weekday: 'short' })} · ${footprintSummary(day, t)}`}
        actions={<HeaderActionButton icon={X} label={t('Close')} onClick={onClose} />}
      />
      {day.sessions.length > 0 && (
        <ul className="dt-cal-detail-links">
          {day.sessions.map(session => (
            <li key={session.id}>
              <Link href={`/chat/${encodeURIComponent(session.id)}`} prefetch={false}>
                <MessageSquare aria-hidden size={14} strokeWidth={1.8} />
                <span className="min-w-0 flex-1 truncate">
                  {session.title || t('Untitled conversation')}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {!day.sessions.length && <Row icon={Footprints}>{footprintSummary(day, t)}</Row>}
    </div>
  )
}

/** Everything on one day, for a month cell that overflowed. */
export function DayList({
  day,
  items,
  onOpen,
  onClose,
  renderChip,
}: {
  day: Date
  items: CalendarItem[]
  onOpen: (item: CalendarItem, element: HTMLElement) => void
  onClose: () => void
  renderChip: (item: CalendarItem, onClick: (element: HTMLElement) => void) => ReactNode
}) {
  const { t, i18n } = useTranslation()
  return (
    <div className="dt-cal-detail">
      <div className="dt-cal-detail-actions">
        <HeaderActionButton icon={X} label={t('Close')} onClick={onClose} />
      </div>
      <p className="dt-cal-daylist-title">
        {formatDate(day, i18n.language, { weekday: 'long', month: 'long', day: 'numeric' })}
      </p>
      <div className="dt-cal-daylist">
        {items.map(item => (
          <div key={item.key}>{renderChip(item, element => onOpen(item, element))}</div>
        ))}
      </div>
    </div>
  )
}

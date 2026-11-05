'use client'

import { useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { AlignLeft, Bell, Clock, MapPin, Plus, Repeat2, X } from 'lucide-react'
import HeaderActionButton from '@/features/chat/components/HeaderActionButton'
import { addDays, dateKey, formatWeekday, fromDateKey } from '../model/dates'
import { lastDay, withAllDay, type EventDraft } from '../model/draft'
import {
  buildRule,
  defaultRule,
  detectPreset,
  parseRule,
  presetRule,
  type Frequency,
  type RepeatPreset,
} from '../model/recurrence'
import type { CalendarEntry, EditScope } from '../transport/api'
import { calendarName, CALENDAR_COLORS } from './CalendarRail'

function dateValue(date: Date, allDay: boolean) {
  if (allDay) return dateKey(date)
  return `${dateKey(date)}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function EventEditor({
  initial,
  calendars,
  recurring,
  busy,
  error,
  onSave,
  onClose,
}: {
  initial: EventDraft
  calendars: CalendarEntry[]
  recurring: boolean
  busy: boolean
  error: string
  onSave: (draft: EventDraft, scope: EditScope) => void
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const [draft, setDraft] = useState(initial)
  const [scope, setScope] = useState<EditScope>('this')
  const [preset, setPreset] = useState<RepeatPreset>(detectPreset(initial.rrule, initial.start))
  const [rule, setRule] = useState(parseRule(initial.rrule) ?? defaultRule('WEEKLY', initial.start))
  const [customReminder, setCustomReminder] = useState(10)
  const change = (patch: Partial<EventDraft>) => setDraft(d => ({ ...d, ...patch }))
  const applyRule = (next: typeof rule) => {
    setRule(next)
    if (recurring) setScope('all')
    change({ rrule: buildRule(next, draft.allDay) })
  }
  const valid = Number.isFinite(draft.start.getTime()) && draft.end > draft.start
  const [addingReminder, setAddingReminder] = useState(false)
  const calendarId = draft.calendarId ?? calendars.find(c => c.is_default)?.id ?? ''
  const calendarColor = calendars.find(c => c.id === calendarId)?.color ?? CALENDAR_COLORS[0]
  return (
    <form
      className="dt-cal-editor is-quick"
      onSubmit={event => {
        event.preventDefault()
        if (valid && !busy)
          onSave(
            draft,
            recurring ? (draft.rrule !== initial.rrule && scope === 'this' ? 'all' : scope) : 'all'
          )
      }}
    >
      <div className="dt-cal-editor-head">
        <span className="dt-cal-editor-kicker">{t(recurring ? 'Edit event' : 'New event')}</span>
        <HeaderActionButton icon={X} label={t('Close')} onClick={onClose} />
      </div>
      <fieldset disabled={busy}>
        <input
          autoFocus
          className="dt-cal-title-input"
          aria-label={t('Event title')}
          placeholder={t('Add a title')}
          maxLength={200}
          value={draft.title}
          onChange={e => change({ title: e.target.value })}
        />
        <div className="dt-cal-field">
          <Clock aria-hidden size={15} />
          <div className="dt-cal-field-body">
            <div className="dt-cal-when">
              <input
                required
                aria-label={t('Starts')}
                type={draft.allDay ? 'date' : 'datetime-local'}
                value={dateValue(draft.start, draft.allDay)}
                onChange={e => {
                  if (!e.target.value) return
                  const start = draft.allDay ? fromDateKey(e.target.value) : new Date(e.target.value)
                  change({
                    start,
                    end:
                      start >= draft.end
                        ? new Date(start.getTime() + (draft.end.getTime() - draft.start.getTime()))
                        : draft.end,
                  })
                }}
              />
              <span aria-hidden>→</span>
              <input
                required
                aria-label={t('Ends')}
                type={draft.allDay ? 'date' : 'datetime-local'}
                value={dateValue(lastDay(draft), draft.allDay)}
                onChange={e => {
                  if (e.target.value)
                    change({
                      end: draft.allDay
                        ? addDays(fromDateKey(e.target.value), 1)
                        : new Date(e.target.value),
                    })
                }}
              />
            </div>
            <div className="dt-cal-when-options">
              <label className="dt-cal-switch">
                <input
                  type="checkbox"
                  checked={draft.allDay}
                  onChange={e => setDraft(withAllDay(draft, e.target.checked))}
                />
                <span aria-hidden />
                {t('All day')}
              </label>
              <select
                aria-label={t('Repeat')}
                className="dt-cal-inline-select"
                value={preset}
                onChange={e => {
                  const p = e.target.value as RepeatPreset
                  setPreset(p)
                  if (recurring) setScope('all')
                  change({
                    rrule:
                      p === 'custom'
                        ? buildRule(rule, draft.allDay)
                        : presetRule(p, draft.start, draft.allDay),
                  })
                }}
              >
                {(
                  [
                    ['none', 'Does not repeat'],
                    ['daily', 'Daily'],
                    ['weekdays', 'Every weekday'],
                    ['weekly', 'Weekly'],
                    ['monthly', 'Monthly'],
                    ['monthlyWeekday', 'Monthly on this weekday'],
                    ['yearly', 'Yearly'],
                    ['custom', 'Custom repeat'],
                  ] as const
                ).map(([value, label]) => (
                  <option key={value} value={value}>
                    {t(label)}
                  </option>
                ))}
              </select>
            </div>
            {preset === 'custom' && (
              <div className="dt-cal-repeat-editor">
                <div className="dt-cal-repeat-line">
                  {t('Every')}
                  <input
                    aria-label={t('Every')}
                    type="number"
                    min={1}
                    max={1000}
                    value={rule.interval}
                    onChange={e =>
                      applyRule({ ...rule, interval: Math.max(1, Number(e.target.value)) })
                    }
                  />
                  <select
                    aria-label={t('Frequency')}
                    className="dt-cal-inline-select"
                    value={rule.freq}
                    onChange={e => applyRule({ ...rule, freq: e.target.value as Frequency })}
                  >
                    {(['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'] as const).map(f => (
                      <option key={f} value={f}>
                        {t({ DAILY: 'Days', WEEKLY: 'Weeks', MONTHLY: 'Months', YEARLY: 'Years' }[f])}
                      </option>
                    ))}
                  </select>
                </div>
                {rule.freq === 'WEEKLY' && (
                  <div className="dt-cal-weekdays">
                    {Array.from({ length: 7 }, (_, i) => (
                      <button
                        key={i}
                        type="button"
                        aria-pressed={rule.byDay.includes(i)}
                        onClick={() =>
                          applyRule({
                            ...rule,
                            byDay: rule.byDay.includes(i)
                              ? rule.byDay.filter(d => d !== i)
                              : [...rule.byDay, i],
                          })
                        }
                      >
                        {formatWeekday(new Date(2026, 9, 18 + i), i18n.language)}
                      </button>
                    ))}
                  </div>
                )}
                <div className="dt-cal-repeat-line">
                  {t('Repeat ends')}
                  <select
                    aria-label={t('Repeat ends')}
                    className="dt-cal-inline-select"
                    value={rule.end.kind}
                    onChange={e =>
                      applyRule({
                        ...rule,
                        end:
                          e.target.value === 'count'
                            ? { kind: 'count', count: 10 }
                            : e.target.value === 'until'
                              ? { kind: 'until', date: dateKey(addDays(draft.start, 30)) }
                              : { kind: 'never' },
                      })
                    }
                  >
                    <option value="never">{t('Never')}</option>
                    <option value="until">{t('On date')}</option>
                    <option value="count">{t('After occurrences')}</option>
                  </select>
                  {rule.end.kind === 'count' && (
                    <input
                      aria-label={t('Occurrence count')}
                      type="number"
                      min={1}
                      max={10000}
                      value={rule.end.count}
                      onChange={e =>
                        applyRule({
                          ...rule,
                          end: { kind: 'count', count: Math.max(1, Number(e.target.value)) },
                        })
                      }
                    />
                  )}
                  {rule.end.kind === 'until' && (
                    <input
                      aria-label={t('Repeat until')}
                      type="date"
                      min={dateKey(draft.start)}
                      value={rule.end.date}
                      onChange={e =>
                        applyRule({ ...rule, end: { kind: 'until', date: e.target.value } })
                      }
                    />
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="dt-cal-field">
          <span
            aria-hidden
            className="dt-cal-field-dot"
            style={{ background: draft.color ?? calendarColor }}
          />
          <div className="dt-cal-field-body dt-cal-field-row">
            <select
              aria-label={t('Calendar')}
              className="dt-cal-inline-select"
              value={calendarId}
              onChange={e => change({ calendarId: e.target.value })}
            >
              {calendars.map(c => (
                <option key={c.id} value={c.id}>
                  {calendarName(c, t)}
                </option>
              ))}
            </select>
            <div className="dt-cal-colors" role="radiogroup" aria-label={t('Event color')}>
              <button
                type="button"
                role="radio"
                aria-checked={!draft.color}
                aria-label={t('Calendar color')}
                className="is-default"
                style={{ '--ev': calendarColor } as CSSProperties}
                onClick={() => change({ color: null })}
              />
              {CALENDAR_COLORS.filter(c => c !== calendarColor).map(c => (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={draft.color === c}
                  aria-label={c}
                  style={{ '--ev': c } as CSSProperties}
                  onClick={() => change({ color: c })}
                />
              ))}
            </div>
          </div>
        </div>
        <div className="dt-cal-field">
          <MapPin aria-hidden size={15} />
          <input
            className="dt-cal-field-input"
            aria-label={t('Location')}
            placeholder={t('Add location')}
            value={draft.location}
            maxLength={300}
            onChange={e => change({ location: e.target.value })}
          />
        </div>
        <div className="dt-cal-field is-top">
          <AlignLeft aria-hidden size={15} />
          <textarea
            className="dt-cal-field-input"
            aria-label={t('Notes')}
            placeholder={t('Add notes')}
            rows={2}
            maxLength={5000}
            value={draft.notes}
            onChange={e => change({ notes: e.target.value })}
          />
        </div>
        <div className="dt-cal-field">
          <Bell aria-hidden size={15} />
          <div className="dt-cal-field-body dt-cal-reminder-chips" aria-label={t('Reminders')}>
            {draft.reminders.map(minutes => (
              <span className="dt-cal-reminder-chip" key={minutes}>
                {minutes < 0
                  ? t('On the day at 09:00')
                  : t('{{minutes}} minutes before', { minutes })}
                <button
                  type="button"
                  aria-label={t('Remove reminder')}
                  onClick={() => change({ reminders: draft.reminders.filter(n => n !== minutes) })}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
            {draft.reminders.length < 5 &&
              (addingReminder ? (
                <span className="dt-cal-reminder-add">
                  <input
                    autoFocus
                    aria-label={t('Minutes before')}
                    type="number"
                    min={0}
                    max={40320}
                    value={customReminder}
                    onChange={e => setCustomReminder(Number(e.target.value))}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        change({ reminders: [...new Set([...draft.reminders, customReminder])] })
                        setAddingReminder(false)
                      }
                      if (e.key === 'Escape') setAddingReminder(false)
                    }}
                  />
                  {t('minutes before')}
                  <button
                    type="button"
                    onClick={() => {
                      change({ reminders: [...new Set([...draft.reminders, customReminder])] })
                      setAddingReminder(false)
                    }}
                  >
                    {t('Add reminder')}
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  className="dt-cal-ghost-button"
                  onClick={() => setAddingReminder(true)}
                >
                  <Plus size={13} />
                  {t(draft.reminders.length ? 'Add reminder' : 'Add a reminder')}
                </button>
              ))}
            {draft.allDay && !draft.reminders.includes(-540) && draft.reminders.length < 5 && (
              <button
                type="button"
                className="dt-cal-ghost-button"
                onClick={() => change({ reminders: [...draft.reminders, -540] })}
              >
                {t('On the day at 09:00')}
              </button>
            )}
          </div>
        </div>
        {recurring && (
          <div className="dt-cal-field">
            <Repeat2 aria-hidden size={15} />
            <ScopeSelect
              scope={scope}
              onChange={setScope}
              allowThis={draft.rrule === initial.rrule}
            />
          </div>
        )}
      </fieldset>
      {!valid && (
        <p role="alert" className="dt-cal-editor-error">
          {t('The end must be after the start.')}
        </p>
      )}
      {error && (
        <p role="alert" className="dt-cal-editor-error">
          {error}
        </p>
      )}
      <div className="dt-cal-editor-footer">
        <button type="button" onClick={onClose} disabled={busy}>
          {t('Cancel')}
        </button>
        <button className="dt-cal-primary" disabled={busy || !valid} type="submit">
          {t(busy ? 'Saving…' : 'Save')}
        </button>
      </div>
    </form>
  )
}

export function ScopeSelect({
  scope,
  onChange,
  allowThis = true,
}: {
  scope: EditScope
  onChange: (scope: EditScope) => void
  allowThis?: boolean
}) {
  const { t } = useTranslation()
  return (
    <label>
      {t('Apply to')}
      <select value={scope} onChange={e => onChange(e.target.value as EditScope)}>
        <option value="this" disabled={!allowThis}>
          {t('This event')}
        </option>
        <option value="following">{t('This and following events')}</option>
        <option value="all">{t('All events in the series')}</option>
      </select>
    </label>
  )
}

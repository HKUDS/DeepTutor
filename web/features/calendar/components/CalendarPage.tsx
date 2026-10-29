'use client'

import { browserStorage } from '@/shared/storage'
import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, Plus, Search, PanelLeft, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { PageHeader } from '@/components/layout/FeaturePage'
import HeaderActionButton from '@/features/chat/components/HeaderActionButton'
import { PageBarSlot, usePageBarOffers } from '@/components/layout/PageChrome'
import { useActiveWorkspaceId } from '@/hooks/useActiveWorkspaceId'
import { useTaskBoard } from '@/lib/task-board-store'
import { DEFAULT_TASK_COLORS, updateTaskCard } from '@/lib/task-board-api'
import * as api from '../transport/api'
import {
  noteCalendarRevision,
  refreshCalendars,
  useCalendars,
  useTaskBlocks,
  useOccurrences,
  useLayers,
} from '../store/calendar-store'
import {
  addDays,
  addMonths,
  atMinutes,
  browserTimeZone,
  dateKey,
  formatDate,
  fromDateKey,
  monthWeeks,
  startOfDay,
  startOfWeek,
  weekStartsOn,
} from '../model/dates'
import {
  blankDraft,
  draftChanges,
  draftFromOccurrence,
  draftToInput,
  type EventDraft,
} from '../model/draft'
import {
  buildItems,
  DEFAULT_LAYERS,
  footprintsByDay,
  type CalendarItem,
  type EventItem,
  type LayerToggles,
} from '../model/items'
import { AnchoredPopover, anchorOf, type Anchor } from './AnchoredPopover'
import { CalendarRail } from './CalendarRail'
import { TimeGrid, type GridDraft } from './TimeGrid'
import { MonthView } from './MonthView'
import { AgendaView, SearchResults } from './AgendaView'
import {
  EventDetails,
  TaskDetails,
  ReviewDetails,
  AutomationDetails,
  FootprintDetails,
} from './ItemDetails'
import { EventEditor, ScopeSelect } from './EventEditor'
import './calendar.css'

type View = 'day' | 'week' | 'month' | 'agenda'
type Panel = { anchor: Anchor } & (
  | { kind: 'detail'; item: CalendarItem }
  | { kind: 'footprint'; day: api.FootprintDay }
  | { kind: 'edit'; draft: EventDraft; original?: EventItem }
  | { kind: 'delete'; item: EventItem }
  | { kind: 'calendar-delete'; calendar: api.CalendarEntry }
  | { kind: 'move'; item: EventItem; start: Date; end: Date }
)
const center: Anchor = { top: 110, bottom: 140, left: 280, right: 280 }

export default function CalendarPage() {
  const { t, i18n } = useTranslation()
  const hasInstance = usePageBarOffers('instance')
  const hasActions = usePageBarOffers('actions')
  const inBar = hasInstance && hasActions
  const workspaceId = useActiveWorkspaceId()
  const { board } = useTaskBoard()
  const blocks = useTaskBlocks(workspaceId)
  const { calendars, error: calendarError } = useCalendars()
  const [cursor, setCursor] = useState(() => new Date())
  const [view, setView] = useState<View>('month')
  const [now, setNow] = useState(() => new Date())
  const [toggles, setToggles] = useState<LayerToggles>(DEFAULT_LAYERS)
  const [rail, setRail] = useState(true)
  const [panel, setPanel] = useState<Panel | null>(null)
  const [scope, setScope] = useState<api.EditScope>('this')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [undo, setUndo] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<api.SearchHit[] | null>(null)
  const [searching, setSearching] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(
    'unsupported'
  )
  const weekStart = weekStartsOn(i18n.language)
  const weeks = useMemo(() => monthWeeks(cursor, weekStart), [cursor, weekStart])
  const first =
    view === 'month'
      ? weeks[0][0]
      : view === 'week'
        ? startOfWeek(cursor, weekStart)
        : startOfDay(cursor)
  const length =
    view === 'month' ? weeks.length * 7 : view === 'week' ? 7 : view === 'agenda' ? 30 : 1
  const last = addDays(first, length)
  const range = { start: first.toISOString(), end: last.toISOString(), tz: browserTimeZone() }
  const occurrences = useOccurrences(range)
  const layers = useLayers(range, workspaceId, true)
  const entries = calendars ?? []
  const items = buildItems({
    occurrences: occurrences.occurrences ?? [],
    calendars: entries,
    tasks: board?.cards ?? [],
    taskColors: board?.colors ?? DEFAULT_TASK_COLORS,
    layers: layers.layers,
    toggles,
  })
  const footprints = footprintsByDay(layers.layers, toggles.footprints)
  const days = Array.from({ length: view === 'day' ? 1 : 7 }, (_, i) => addDays(first, i))
  useEffect(() => {
    const media = window.matchMedia('(max-width: 700px)')
    const update = () => setRail(!media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000)
    setPermission(typeof Notification === 'undefined' ? 'unsupported' : Notification.permission)
    try {
      const prefs = JSON.parse(browserStorage.readRaw('local', 'deeptutor.calendar.preferences') ?? 'null')
      if (prefs) {
        if (['day', 'week', 'month', 'agenda'].includes(prefs.view)) setView(prefs.view)
        if (prefs.layers) setToggles({ ...DEFAULT_LAYERS, ...prefs.layers })
      }
    } catch {}
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    browserStorage.writeRaw('local',
      'deeptutor.calendar.preferences',
      JSON.stringify({ view, layers: toggles })
    )
  }, [view, toggles])
  useEffect(() => {
    if (!query.trim()) {
      setHits(null)
      return
    }
    const controller = new AbortController()
    setSearching(true)
    const timer = setTimeout(() => {
      api
        .searchEvents(query.trim(), controller.signal)
        .then(r => {
          if (controller.signal.aborted) return
          setHits(r.events)
          setSearching(false)
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setSearching(false)
            setError(t('Could not load calendar.'))
          }
        })
    }, 250)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query, t])
  useEffect(() => {
    setError('')
    setScope('this')
  }, [panel?.kind])
  const close = () => {
    if (!lock.current) setPanel(null)
  }
  const create = (grid: GridDraft, anchor: Anchor = center) => {
    setError('')
    setPanel({
      kind: 'edit',
      anchor,
      draft: blankDraft(
        grid.start,
        grid.end,
        grid.allDay,
        entries.find(c => c.is_default)?.id ?? null
      ),
    })
  }
  const newEvent = (anchor?: Anchor) => {
    const start = atMinutes(cursor, now.getHours() * 60 + 60)
    create({ start, end: new Date(start.getTime() + 3600_000), allDay: false }, anchor)
  }
  const navigate = (direction: number) => {
    setPanel(null)
    setCursor(
      view === 'month'
        ? addMonths(cursor, direction)
        : addDays(cursor, direction * (view === 'week' ? 7 : view === 'agenda' ? 30 : 1))
    )
  }
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        e.defaultPrevented ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey ||
        panel ||
        (e.target as HTMLElement)?.closest?.('input,textarea,select,[contenteditable="true"]')
      )
        return
      const k = e.key.toLowerCase()
      if (k === 't') {
        setCursor(new Date())
        e.preventDefault()
      } else if (k === 'c') {
        newEvent()
        e.preventDefault()
      } else if (k === '/') {
        setSearchOpen(true)
        requestAnimationFrame(() => searchRef.current?.focus())
        e.preventDefault()
      } else if (k === 'arrowleft') {
        navigate(-1)
        e.preventDefault()
      } else if (k === 'arrowright') {
        navigate(1)
        e.preventDefault()
      } else if (['d', 'w', 'm', 'a'].includes(k)) {
        setView(({ d: 'day', w: 'week', m: 'month', a: 'agenda' } as Record<string, View>)[k])
        e.preventDefault()
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  })
  async function act(
    operation: () => Promise<{ revision?: number; undo_token?: string } | unknown>,
    done?: () => void
  ) {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    setError('')
    try {
      const response = (await operation()) as { revision?: number; undo_token?: string }
      if (response?.revision !== undefined && !('cards' in response))
        noteCalendarRevision(response.revision)
      if (response?.undo_token) setUndo(response.undo_token)
      done?.()
    } catch (e) {
      setError(
        e instanceof api.CalendarRequestError && e.detail
          ? e.detail
          : t('Could not save calendar changes.')
      )
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  const openItem = (item: CalendarItem, anchor: Anchor) =>
    setPanel({ kind: 'detail', item, anchor })
  const openFootprint = (day: api.FootprintDay, anchor: Anchor) =>
    setPanel({ kind: 'footprint', day, anchor })
  const openDay = (day: Date) => {
    setCursor(day)
    setView('day')
    setQuery('')
    setPanel(null)
  }
  const move = (item: EventItem, start: Date, end: Date) => {
    if (item.occurrence.recurring) setPanel({ kind: 'move', item, start, end, anchor: center })
    else
      void act(() =>
        api.updateEvent(item.occurrence.event_id, {
          start: item.allDay ? dateKey(start) : start.toISOString(),
          end: item.allDay ? dateKey(end) : end.toISOString(),
        })
      )
  }
  const drop = (id: string, target: GridDraft) => {
    const card = board?.cards.find(c => c.id === id)
    if (!card || card.archived) return
    if (target.allDay) {
      void act(() => updateTaskCard(id, { due_date: dateKey(target.start) }))
      return
    }
    const draft = {
      ...blankDraft(target.start, target.end, false, entries.find(c => c.is_default)?.id ?? null),
      title: card.title,
      taskId: id,
      taskWorkspaceId: workspaceId,
    }
    void act(() => api.createEvent(draftToInput(draft)))
  }
  const shared = {
    items,
    footprints,
    now,
    selectedKey: panel?.kind === 'detail' ? panel.item.key : null,
    onOpenItem: openItem,
    onOpenFootprint: openFootprint,
    onOpenDay: openDay,
  }
  const editing = panel?.kind === 'edit' ? panel : null
  const gridProps = {
    ...shared,
    draft: editing
      ? { start: editing.draft.start, end: editing.draft.end, allDay: editing.draft.allDay }
      : null,
    onCreate: create,
    onReschedule: move,
    onDropTask: drop,
  }
  const heading = formatDate(cursor, i18n.language, {
    year: 'numeric',
    month: 'long',
    ...(view === 'day' ? { day: 'numeric' } : {}),
  })
  // Where the layout has a page bar, the toolbar moves up into it — the
  // navigation beside the feature crumb, the view tools on the right — so the
  // calendar itself starts one row higher.
  const lead = (
    <>
      <HeaderActionButton
        icon={PanelLeft}
        label={t('Calendar sidebar')}
        active={rail}
        onClick={() => setRail(!rail)}
      />
      <button
        className="dt-cal-today"
        onClick={() => {
          setCursor(new Date())
          setQuery('')
        }}
      >
        {t('Today')}
      </button>
      <div className="dt-cal-step">
        <HeaderActionButton icon={ChevronLeft} label={t('Previous')} onClick={() => navigate(-1)} />
        <HeaderActionButton icon={ChevronRight} label={t('Next')} onClick={() => navigate(1)} />
      </div>
      <h2>{heading}</h2>
    </>
  )
  const tools = (
    <>
      <div className={`dt-cal-search ${searchOpen || query ? 'is-open' : ''}`}>
        {searchOpen || query ? (
          <>
            <Search size={14} aria-hidden />
            <input
              ref={searchRef}
              autoFocus
              aria-label={t('Search calendar')}
              placeholder={t('Search events…')}
              value={query}
              maxLength={200}
              onChange={e => setQuery(e.target.value)}
              onBlur={() => {
                if (!query) setSearchOpen(false)
              }}
              onKeyDown={e => {
                if (e.key === 'Escape') {
                  setQuery('')
                  setSearchOpen(false)
                }
              }}
            />
            {query && (
              <HeaderActionButton
                icon={X}
                label={t('Clear search')}
                onClick={() => {
                  setQuery('')
                  setSearchOpen(false)
                }}
              />
            )}
          </>
        ) : (
          <HeaderActionButton
            icon={Search}
            label={t('Search calendar')}
            title={`${t('Search calendar')}  /`}
            onClick={() => setSearchOpen(true)}
          />
        )}
      </div>
      <div className="dt-cal-views" role="tablist" aria-label={t('Calendar view')}>
        {(['day', 'week', 'month', 'agenda'] as const).map(v => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => {
              setView(v)
              setPanel(null)
            }}
          >
            {t({ day: 'Day', week: 'Week', month: 'Month', agenda: 'Agenda' }[v])}
          </button>
        ))}
      </div>
      <button
        className="dt-cal-primary dt-cal-new"
        disabled={!calendars}
        onClick={event => newEvent(anchorOf(event.currentTarget) ?? undefined)}
      >
        <Plus size={15} strokeWidth={2} />
        <span>{t('New event')}</span>
      </button>
    </>
  )
  return (
    <section
      className={`dt-calendar ${inBar ? 'has-bar-toolbar' : ''}`}
      aria-label={t('Calendar')}
      aria-busy={busy}
    >
      <div className="dt-cal-page-title">
        <PageHeader title={t('Calendar')} icon={CalendarDays} />
      </div>
      {inBar ? (
        <>
          <PageBarSlot name="instance">
            <div className="dt-cal-toolbar is-in-bar">{lead}</div>
          </PageBarSlot>
          <PageBarSlot name="actions">
            <div className="dt-cal-toolbar is-in-bar is-tools">{tools}</div>
          </PageBarSlot>
        </>
      ) : (
        <div className="dt-cal-toolbar">
          {lead}
          {tools}
        </div>
      )}
      {(calendarError || occurrences.error || layers.error) && (
        <div role="alert" className="dt-cal-alert is-error">
          <span>{t('Could not load calendar.')}</span>
          <button
            onClick={() => {
              void refreshCalendars()
              occurrences.retry()
              layers.reload()
            }}
          >
            {t('Retry')}
          </button>
        </div>
      )}
      {error && !editing && (
        <div role="alert" className="dt-cal-alert is-error">
          <span>{error}</span>
        </div>
      )}
      {undo && (
        <div role="status" className="dt-cal-alert">
          <span>{t('Event deleted')}</span>
          <button
            disabled={busy}
            onClick={() =>
              void act(
                () => api.restoreEvent(undo),
                () => setUndo(null)
              )
            }
          >
            {t('Undo')}
          </button>
          <button onClick={() => setUndo(null)}>{t('Dismiss')}</button>
        </div>
      )}
      <div className="dt-cal-workspace">
        {rail && (
          <CalendarRail
            cursor={cursor}
            range={[dateKey(first), dateKey(last)]}
            weekStart={weekStart}
            now={now}
            onPick={openDay}
            tasks={board?.cards.filter(card => !blocks[card.id]) ?? null}
            taskColors={board?.colors ?? DEFAULT_TASK_COLORS}
            calendars={entries}
            onUpdateCalendar={(c, changes) => void act(() => api.updateCalendar(c.id, changes))}
            onCreateCalendar={(name, color) => void act(() => api.createCalendar({ name, color }))}
            onDeleteCalendar={calendar =>
              setPanel({ kind: 'calendar-delete', calendar, anchor: center })
            }
            layers={toggles}
            onToggleLayer={key => setToggles(s => ({ ...s, [key]: !s[key] }))}
            notifications={permission}
            onEnableNotifications={() => {
              void Notification.requestPermission().then(setPermission)
            }}
          />
        )}
        <main className="dt-cal-main">
          {query.trim() ? (
            <SearchResults
              query={query}
              hits={hits}
              loading={searching}
              calendars={entries}
              onPick={hit => {
                const start = hit.all_day
                  ? fromDateKey(hit.next_start ?? hit.start)
                  : new Date(hit.next_start ?? hit.start)
                openDay(start)
              }}
            />
          ) : view === 'month' ? (
            <MonthView
              {...gridProps}
              weeks={weeks}
              month={cursor.getMonth()}
              onShowMore={openDay}
            />
          ) : view === 'agenda' ? (
            <AgendaView {...shared} from={first} days={30} />
          ) : (
            <TimeGrid {...gridProps} days={days} />
          )}
        </main>
      </div>
      {panel && (
        <AnchoredPopover
          anchor={panel.anchor}
          onClose={close}
          width={panel.kind === 'edit' ? 410 : 350}
          label={t(panel.kind === 'edit' ? 'Edit event' : 'Calendar details')}
        >
          {panel.kind === 'edit' ? (
            <EventEditor
              initial={panel.draft}
              calendars={entries}
              recurring={!!panel.original?.occurrence.recurring}
              busy={busy}
              error={error}
              onClose={close}
              onSave={(draft, chosen) =>
                void act(
                  () =>
                    panel.original
                      ? api.updateEvent(
                          panel.original.occurrence.event_id,
                          draftChanges(draftFromOccurrence(panel.original.occurrence), draft),
                          { scope: chosen, occurrence: panel.original.occurrence.occurrence }
                        )
                      : api.createEvent(draftToInput(draft)),
                  () => setPanel(null)
                )
              }
            />
          ) : panel.kind === 'footprint' ? (
            <FootprintDetails day={panel.day} onClose={close} />
          ) : panel.kind === 'detail' ? (
            <>
              {panel.item.kind === 'event' && (
                <EventDetails
                  item={panel.item}
                  calendars={entries}
                  task={board?.cards.find(
                    c =>
                      c.id === (panel.item as EventItem).occurrence.task_id &&
                      (panel.item as EventItem).occurrence.task_workspace_id === workspaceId
                  )}
                  onClose={close}
                  onEdit={() => {
                    if (panel.item.kind === 'event')
                      setPanel({
                        kind: 'edit',
                        draft: draftFromOccurrence(panel.item.occurrence),
                        original: panel.item,
                        anchor: panel.anchor,
                      })
                  }}
                  onDuplicate={() => {
                    if (panel.item.kind === 'event')
                      setPanel({
                        kind: 'edit',
                        draft: { ...draftFromOccurrence(panel.item.occurrence), rrule: null },
                        anchor: panel.anchor,
                      })
                  }}
                  onDelete={() => {
                    if (panel.item.kind === 'event')
                      setPanel({ kind: 'delete', item: panel.item, anchor: panel.anchor })
                  }}
                  onCompleteTask={card =>
                    void act(
                      () => updateTaskCard(card.id, { status: 'done' }),
                      () => setPanel(null)
                    )
                  }
                />
              )}
              {panel.item.kind === 'task' && (
                <TaskDetails
                  sessionIds={board?.session_links
                    .filter(link =>
                      link.task_ids.includes(panel.item.kind === 'task' ? panel.item.card.id : '')
                    )
                    .map(link => link.session_id)}
                  item={panel.item}
                  onClose={close}
                  onToggleDone={() => {
                    if (panel.item.kind === 'task')
                      void act(
                        () =>
                          updateTaskCard(panel.item.kind === 'task' ? panel.item.card.id : '', {
                            status:
                              panel.item.kind === 'task' && panel.item.card.status === 'done'
                                ? 'todo'
                                : 'done',
                          }),
                        () => setPanel(null)
                      )
                  }}
                  onClearDate={() => {
                    if (panel.item.kind === 'task')
                      void act(
                        () =>
                          updateTaskCard(panel.item.kind === 'task' ? panel.item.card.id : '', {
                            due_date: null,
                          }),
                        () => setPanel(null)
                      )
                  }}
                  onSchedule={() => {
                    if (panel.item.kind === 'task') {
                      const start = atMinutes(panel.item.start, 9 * 60)
                      setPanel({
                        kind: 'edit',
                        anchor: panel.anchor,
                        draft: {
                          ...blankDraft(
                            start,
                            new Date(start.getTime() + 3600_000),
                            false,
                            entries.find(c => c.is_default)?.id ?? null
                          ),
                          title: panel.item.card.title,
                          taskId: panel.item.card.id,
                          taskWorkspaceId: workspaceId,
                        },
                      })
                    }
                  }}
                />
              )}
              {panel.item.kind === 'review' && <ReviewDetails item={panel.item} onClose={close} />}
              {panel.item.kind === 'automation' && (
                <AutomationDetails
                  item={panel.item}
                  onClose={close}
                  onCancel={() => {
                    if (panel.item.kind === 'automation')
                      void act(
                        () =>
                          api.cancelAutomation(
                            panel.item.kind === 'automation' ? panel.item.run.job_id : ''
                          ),
                        () => {
                          setPanel(null)
                          layers.reload()
                        }
                      )
                  }}
                />
              )}
            </>
          ) : (
            <div className="dt-cal-editor">
              <strong>
                {t(
                  panel.kind === 'move'
                    ? 'Reschedule event'
                    : panel.kind === 'calendar-delete'
                      ? 'Delete calendar and its events?'
                      : 'Delete event?'
                )}
              </strong>
              {panel.kind !== 'calendar-delete' && panel.item.occurrence.recurring && (
                <ScopeSelect scope={scope} onChange={setScope} />
              )}
              <div className="dt-cal-editor-footer">
                <button disabled={busy} onClick={close}>
                  {t('Cancel')}
                </button>
                <button
                  className="dt-cal-primary"
                  disabled={busy}
                  onClick={() =>
                    void act(
                      () => {
                        if (panel.kind === 'calendar-delete')
                          return api.deleteCalendar(panel.calendar.id)
                        if (panel.kind === 'delete')
                          return api.deleteEvent(panel.item.occurrence.event_id, {
                            scope,
                            occurrence: panel.item.occurrence.occurrence,
                          })
                        if (panel.kind === 'move')
                          return api.updateEvent(
                            panel.item.occurrence.event_id,
                            {
                              start: panel.item.allDay
                                ? dateKey(panel.start)
                                : panel.start.toISOString(),
                              end: panel.item.allDay ? dateKey(panel.end) : panel.end.toISOString(),
                            },
                            { scope, occurrence: panel.item.occurrence.occurrence }
                          )
                        return Promise.resolve()
                      },
                      () => setPanel(null)
                    )
                  }
                >
                  {t(panel.kind === 'move' ? 'Save' : 'Delete')}
                </button>
              </div>
            </div>
          )}
        </AnchoredPopover>
      )}
    </section>
  )
}

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CalendarPage from '@/features/calendar/components/CalendarPage'
import CalendarRuntime from '@/features/calendar/components/CalendarRuntime'
import TaskBoardRuntime from '@/components/tasks/TaskBoardRuntime'
import { DEFAULT_TASK_COLORS } from '@/lib/task-board-api'
import { dateKey, addDays, addMonths, monthWeeks } from '@/features/calendar/model/dates'
import { buildRule, parseRule } from '@/features/calendar/model/recurrence'
import { layoutDay } from '@/features/calendar/model/layout'
import { draftFromOccurrence, draftToInput } from '@/features/calendar/model/draft'
import type { Occurrence } from '@/features/calendar/transport/api'

const language = { language: 'en' }
const translate = (key: string, values?: Record<string, unknown>) =>
  key.replace(/{{(\w+)}}/g, (_, k) => String(values?.[k] ?? k))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate, i18n: language }) }))
vi.mock('@/hooks/useAuthStatus', () => ({
  useAuthStatus: () => ({
    loading: false,
    learningPolicy: null,
    enabled: false,
    authenticated: true,
  }),
}))
vi.mock('@/hooks/useActiveWorkspaceId', () => ({ useActiveWorkspaceId: () => '' }))

let events: Occurrence[]
let revision: number
let failSave: boolean
const calendar = {
  id: 'default',
  name: '',
  color: '#2f6fde',
  is_default: true,
  visible: true,
  position: 0,
  created_at: '',
  updated_at: '',
}

beforeEach(() => {
  events = []
  revision = 0
  failSave = false
  window.history.replaceState({}, '', '/calendar?dt_workspace=')
  vi.stubGlobal('EventSource', undefined)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url, 'http://localhost').pathname
      if (path === '/api/task-board')
        return Response.json({
          cards: [],
          session_links: [],
          colors: DEFAULT_TASK_COLORS,
          revision: 0,
        })
      if (path === '/api/calendar/calendars')
        return Response.json({ calendars: [calendar], revision })
      if (path === '/api/calendar/task-blocks') return Response.json({})
      if (path === '/api/calendar/layers')
        return Response.json({ workspace_id: '', reviews: [], automations: [], footprints: [] })
      if (path === '/api/calendar/events' && init?.method === 'POST') {
        if (failSave) return Response.json({ detail: 'Save failed' }, { status: 500 })
        const fields = JSON.parse(String(init.body))
        const id = String(++revision)
        events.push({
          ...fields,
          id,
          event_id: id,
          occurrence: fields.start,
          series_id: null,
          recurring: false,
          reminder_times: [],
        })
        return Response.json({ event: events.at(-1), revision })
      }
      if (path === '/api/calendar/events') return Response.json({ occurrences: events, revision })
      if (init?.method === 'DELETE') {
        events = []
        return Response.json({ revision: ++revision, undo_token: 'undo' })
      }
      return Response.json({ revision: ++revision })
    })
  )
})
afterEach(() => vi.unstubAllGlobals())
const mount = () =>
  render(
    <CalendarRuntime>
      <TaskBoardRuntime>
        <CalendarPage />
      </TaskBoardRuntime>
    </CalendarRuntime>
  )

it('creates an event, shows it in the agenda, and deletes it with undo available', async () => {
  mount()
  await waitFor(() => expect(screen.getByRole('button', { name: 'New event' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'New event' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Event title' }), {
    target: { value: 'Study algebra' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(events[0].title).toBe('Study algebra')
  fireEvent.click(screen.getByRole('tab', { name: 'Agenda' }))
  fireEvent.click(await screen.findByRole('button', { name: /Study algebra/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete event' }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
  expect(await screen.findByRole('button', { name: 'Undo' })).toBeInTheDocument()
  expect(events).toHaveLength(0)
})

it('retains the editor draft when saving fails', async () => {
  mount()
  await waitFor(() => expect(screen.getByRole('button', { name: 'New event' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'New event' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Event title' }), {
    target: { value: 'Keep this draft' },
  })
  failSave = true
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Save failed')
  expect(screen.getByRole('textbox', { name: 'Event title' })).toHaveValue('Keep this draft')
  expect(events).toHaveLength(0)
})

it('does not trigger calendar shortcuts while typing in the editor', async () => {
  mount()
  await waitFor(() => expect(screen.getByRole('button', { name: 'New event' })).toBeEnabled())
  fireEvent.keyDown(window, { key: 'c' })
  const title = screen.getByRole('textbox', { name: 'Event title' })
  fireEvent.keyDown(title, { key: 'w' })
  expect(screen.getByRole('tab', { name: 'Month' })).toHaveAttribute('aria-selected', 'true')
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
  await act(async () => {
    fireEvent.keyDown(window, { key: 'w' })
  })
  expect(screen.getByRole('tab', { name: 'Week' })).toHaveAttribute('aria-selected', 'true')
})

describe('calendar models', () => {
  it('clamps month navigation and covers the leap day once', () => {
    expect(dateKey(addMonths(new Date(2024, 0, 31), 1))).toBe('2024-02-29')
    const days = monthWeeks(new Date(2024, 1, 1), 1)
      .flat()
      .map(dateKey)
    expect(days.filter(day => day === '2024-02-29')).toHaveLength(1)
    expect(new Set(days).size).toBe(days.length)
    expect(dateKey(addDays(new Date(2024, 1, 29), 1))).toBe('2024-03-01')
  })
  it('lays simultaneous events in separate columns and reuses freed width', () => {
    const boxes = layoutDay([
      { id: 'a', start: 60, end: 180 },
      { id: 'b', start: 90, end: 120 },
      { id: 'c', start: 240, end: 300 },
    ])
    expect(boxes.find(b => b.id === 'a')!.left).not.toBe(boxes.find(b => b.id === 'b')!.left)
    expect(boxes.find(b => b.id === 'c')!.width).toBe(1)
  })
  it('preserves custom recurrence parts when editing known fields', () => {
    const rule = parseRule('FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR;COUNT=12;WKST=MO')!
    expect(buildRule(rule, false)).toContain('WKST=MO')
    expect(buildRule(rule, false)).toContain('COUNT=12')
  })
  it('preserves the event timezone when editing from another browser zone', () => {
    const occurrence: Occurrence = {
      id: 'test',
      event_id: 'test',
      series_id: null,
      occurrence: '2026-03-29T07:00:00Z',
      recurring: false,
      source: 'user',
      reminder_times: [],
      start: '2026-03-29T07:00:00Z',
      end: '2026-03-29T08:00:00Z',
      all_day: false,
      tzid: 'Europe/Berlin',
      title: 'Meeting',
      notes: '',
      location: '',
      rrule: null,
      reminders: [],
      color: null,
      calendar_id: 'default',
      task_id: null,
      task_workspace_id: null,
    }
    expect(draftToInput(draftFromOccurrence(occurrence)).tzid).toBe('Europe/Berlin')
  })
})

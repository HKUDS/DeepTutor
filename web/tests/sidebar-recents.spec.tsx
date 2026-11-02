import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import OrganizedSessionList from '@/components/sessions/OrganizedSessionList'
import { buildSidebarEntries } from '@/lib/sidebar-entries'
import type { SessionSummary } from '@/lib/session-api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }))
const rows: SessionSummary[] = Array.from({ length: 8 }, (_, index) => ({
  id: `chat-${index}`, session_id: `chat-${index}`, title: `Lesson ${index}`,
  created_at: 1, updated_at: 1, message_count: 2, last_message: '',
  content_workspace_id: 'physics', preferences: {},
}))

it('files every conversation of the workspace under one Recent heading', () => {
  const entries = buildSidebarEntries({ roots: rows, recents: true })
  expect(entries).toHaveLength(1)
  expect(entries[0]).toMatchObject({ kind: 'group', group: 'recent', rows })
})

it('shows five recents, expands older chats and preserves their actions', () => {
  const select = vi.fn()
  const view = render(<OrganizedSessionList sessions={rows} recents
    activeSessionId={null} onSelect={select} onRename={vi.fn()} onDelete={vi.fn()} onOrganize={vi.fn()} />)
  expect(screen.queryByText('Lesson 5')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Show more' }))
  fireEvent.click(screen.getByText('Lesson 7'))
  expect(select).toHaveBeenCalledWith('chat-7')
  // Workspaces are switched in the header; the list carries no workspace groups.
  expect(view.container.querySelector('[data-group-id^="workspace:"]')).toBeNull()
})

it('renders an older active conversation among the recents immediately', () => {
  const view = render(<OrganizedSessionList sessions={rows} recents
    activeSessionId="chat-7" onSelect={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} onOrganize={vi.fn()} />)
  expect(within(view.container).getByText('Lesson 7')).toBeInTheDocument()
  expect(within(view.container).getAllByText(/^Lesson /)).toHaveLength(5)
})

it('lists conversations by day with pinned ones first and filters them by search', () => {
  const now = Date.now() / 1000
  const sessions: SessionSummary[] = [
    { ...rows[0], session_id: 'today', id: 'today', title: 'Vectors today', updated_at: now - 60, created_at: now - 9 * 86400 },
    { ...rows[1], session_id: 'old', id: 'old', title: 'Matrices last month', updated_at: now - 30 * 86400, created_at: now - 30 * 86400 },
    { ...rows[2], session_id: 'pin', id: 'pin', title: 'Pinned plan', updated_at: now - 40 * 86400, created_at: now - 40 * 86400, preferences: { pinned: true } },
  ]
  const view = { sort: 'updatedAt' as const, query: '', searching: false, limit: 30, setSort: vi.fn(), setQuery: vi.fn(), setSearching: vi.fn(), more: vi.fn() }
  const props = { sessions, activeSessionId: null, onSelect: vi.fn(), onRename: vi.fn(), onDelete: vi.fn(), onOrganize: vi.fn() }
  const { container, rerender } = render(<OrganizedSessionList {...props} timeline={view} />)
  const headings = () => [...container.querySelectorAll('.dt-record-group > h2')].map(node => node.textContent)
  expect(headings()).toEqual(['navigation.pinned', 'Today', 'Earlier'])
  expect(container.querySelectorAll('time.dt-record-time')).toHaveLength(3)
  // Ordered by creation, the conversation active today was started last week.
  rerender(<OrganizedSessionList {...props} timeline={{ ...view, sort: 'createdAt' }} />)
  expect(headings()).toEqual(['navigation.pinned', 'Earlier'])
  rerender(<OrganizedSessionList {...props} timeline={{ ...view, query: 'matrices' }} />)
  expect(screen.getByText('Matrices last month')).toBeInTheDocument()
  expect(screen.queryByText('Vectors today')).toBeNull()
  expect(screen.queryByText('Pinned plan')).toBeNull()
})

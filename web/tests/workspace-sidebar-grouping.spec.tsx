import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import OrganizedSessionList from '@/components/courses/OrganizedSessionList'
import { buildSidebarEntries } from '@/lib/sidebar-entries'
import type { SessionSummary } from '@/lib/session-api'
import type { ChatWorkspaceRegistration } from '@/lib/workspaces-api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const workspace: ChatWorkspaceRegistration = {
  workspace_id: 'physics', display_name: 'Physics', kind: 'workspace', archived: false,
  follows_root: true, path: '', status: 'ready', error: '', created_at: '',
}
const rows: SessionSummary[] = Array.from({ length: 8 }, (_, index) => ({
  id: `chat-${index}`, session_id: `chat-${index}`, title: `Lesson ${index}`,
  created_at: 1, updated_at: 1, message_count: 2, last_message: '',
  content_workspace_id: 'physics', preferences: {},
}))

it('groups by storage origin even when legacy preferences disagree', () => {
  const entries = buildSidebarEntries({ roots: [
    rows[0],
    { ...rows[1], content_workspace_id: '', preferences: { workspace_id: 'physics' } },
  ], workspaces: [workspace] })
  expect(entries[0]).toMatchObject({ kind: 'group', group: 'workspace', label: 'Physics', rows: [rows[0]] })
  expect(entries[1]).toMatchObject({ kind: 'group', group: 'recent', rows: [{ session_id: 'chat-1' }] })
})

it('shows a folder group, expands older chats and preserves their actions', () => {
  const select = vi.fn()
  render(<OrganizedSessionList sessions={rows} courses={[]} workspaces={[workspace]} groupWorkspaces
    activeSessionId={null} onSelect={select} onRename={vi.fn()} onDelete={vi.fn()} onOrganize={vi.fn()} />)
  const heading = screen.getByRole('button', { name: 'Physics' })
  expect(heading).toHaveAttribute('aria-expanded', 'true')
  expect(screen.queryByText('Lesson 5')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Show more' }))
  fireEvent.click(screen.getByText('Lesson 7'))
  expect(select).toHaveBeenCalledWith('chat-7')
  fireEvent.click(heading)
  expect(screen.queryByText('Lesson 0')).toBeNull()
})

it('renders an older active conversation inside its group immediately', () => {
  const view = render(<OrganizedSessionList sessions={rows} courses={[]} workspaces={[workspace]} groupWorkspaces
    activeSessionId="chat-7" onSelect={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} onOrganize={vi.fn()} />)
  expect(within(view.container).getByText('Lesson 7')).toBeInTheDocument()
  expect(within(view.container).getAllByText(/^Lesson /)).toHaveLength(5)
})

it('keeps an empty workspace visible and allows starting its first chat', () => {
  const newChat = vi.fn()
  render(<OrganizedSessionList sessions={[]} courses={[]} workspaces={[workspace]} groupWorkspaces
    onNewWorkspaceChat={newChat} activeSessionId={null}
    onSelect={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} onOrganize={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Physics' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'New chat in {{name}}' }))
  expect(newChat).toHaveBeenCalledWith('physics')
})


it('keeps unassigned chats in a peer Recent section with independent five-row limits', () => {
  const unassigned = rows.map((row, index) => ({ ...row, id: `recent-${index}`, session_id: `recent-${index}`, title: `Recent ${index}`, content_workspace_id: '' }))
  const view = render(<OrganizedSessionList sessions={[...unassigned, ...rows]} courses={[]} workspaces={[workspace]} groupWorkspaces
    activeSessionId={null} onSelect={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} onOrganize={vi.fn()} />)
  const workspaceGroup = view.container.querySelector('[data-group-id="workspace:physics"]')! as HTMLElement
  const recentGroup = view.container.querySelector('[data-group-id="recent:unassigned"]')! as HTMLElement
  expect(workspaceGroup.parentElement).toBe(recentGroup.parentElement)
  expect(workspaceGroup.nextElementSibling).toBe(recentGroup)
  expect(within(recentGroup).queryByText('Lesson 0')).toBeNull()
  expect(within(recentGroup).getByText('Recent 4')).toBeInTheDocument()
  expect(within(recentGroup).queryByText('Recent 5')).toBeNull()
  fireEvent.click(within(recentGroup).getByRole('button', { name: 'Show more' }))
  expect(within(recentGroup).getByText('Recent 7')).toBeInTheDocument()
  expect(within(workspaceGroup).queryByText('Lesson 5')).toBeNull()
})

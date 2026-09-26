import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { WorkspaceChatGroups } from '@/components/workspaces/WorkspaceChatGroups'

const fixture = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/lib/session-api', () => ({ listSessions: fixture.list }))
vi.mock('@/lib/workspaces-api', () => ({
  listWorkspaces: async () => [
    { workspace_id: 'physics', display_name: 'Physics', kind: 'workspace', status: 'ready' },
  ],
}))
vi.mock('@/lib/sidebar-layout', () => ({
  readCollapsedGroups: () => [],
  writeCollapsedGroups: vi.fn(),
}))
vi.mock('@/lib/session-events', () => ({ subscribeSessionChanges: () => () => {} }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }))
vi.mock('@/components/SessionList', () => ({
  default: ({ sessions }: { sessions: { session_id: string }[] }) => (
    <div data-testid="rows">{sessions.length}</div>
  ),
}))
afterEach(cleanup)

it('expands workspace history beyond the API page cap without losing rows', async () => {
  const rows = Array.from({ length: 230 }, (_, i) => ({ session_id: `session-${i}` }))
  fixture.list.mockImplementation(async (limit, offset) => rows.slice(offset, offset + limit))
  render(
    <WorkspaceChatGroups
      workspaces={[{ workspace_id: 'physics', display_name: 'Physics', kind: 'workspace', status: 'ready', follows_root: true, path: '/physics', archived: false, error: '', created_at: '' }]}
      refreshToken={0}
      onNewChat={vi.fn()}
      onSelect={vi.fn()}
      onRename={vi.fn()}
      onDelete={vi.fn()}
    />
  )
  await waitFor(() => expect(screen.getByTestId('rows')).toHaveTextContent('5'))
  for (let count = 25; count <= 225; count += 20) {
    fireEvent.click(screen.getByRole('button', { name: 'Show more' }))
    await waitFor(() => expect(screen.getByTestId('rows')).toHaveTextContent(String(count)))
  }
  fireEvent.click(screen.getByRole('button', { name: 'Show more' }))
  await waitFor(() => expect(screen.getByTestId('rows')).toHaveTextContent('230'))
  expect(screen.queryByRole('button', { name: 'Show more' })).toBeNull()
  expect(fixture.list.mock.calls.every(([limit]) => limit <= 200)).toBe(true)
  expect(fixture.list.mock.calls.some(([, offset]) => offset === 200)).toBe(true)
})

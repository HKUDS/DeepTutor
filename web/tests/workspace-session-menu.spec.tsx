import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import OrganizedSessionList from '@/components/courses/OrganizedSessionList'
import type { SessionSummary } from '@/lib/session-api'
import type { ChatWorkspaceRegistration } from '@/lib/workspaces-api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }))
afterEach(cleanup)
const workspace: ChatWorkspaceRegistration = { workspace_id: 'algebra', display_name: 'Algebra', kind: 'workspace', status: 'ready', archived: false, follows_root: true, path: '/algebra', error: '', created_at: '' }
const session: SessionSummary = { id: 'chat-1', session_id: 'chat-1', title: 'Learning algebra', created_at: 1, updated_at: 1, message_count: 1, last_message: '', preferences: { workspace_id: 'algebra' } }
function show(workspaces: ChatWorkspaceRegistration[], onOrganize = vi.fn(), running = false) {
  render(<OrganizedSessionList sessions={[session]} courses={[]} workspaces={workspaces} activeSessionId="chat-1" liveSessionIds={running ? new Set(['chat-1']) : undefined} onSelect={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} onOrganize={onOrganize} />)
  fireEvent.click(screen.getByRole('button', { name: 'Conversation actions' }))
}
it('allows removing an archived binding even when no active workspace exists', async () => {
  const move = vi.fn()
  show([{ ...workspace, archived: true }], move)
  expect(screen.getByRole('menuitem', { name: 'Algebra' })).toBeDisabled()
  await act(async () => { fireEvent.click(screen.getByRole('menuitem', { name: 'No workspace' })) })
  expect(move).toHaveBeenCalledWith('chat-1', { workspace_id: null })
})
it('disables invalid destinations and moving a running conversation', () => {
  show([{ ...workspace, status: 'invalid' }], vi.fn(), true)
  expect(screen.getByRole('menuitem', { name: 'Algebra' })).toBeDisabled()
  expect(screen.getByRole('menuitem', { name: 'No workspace' })).toBeDisabled()
})
it('shows a failed move without claiming that the conversation moved', async () => {
  show([workspace], vi.fn().mockRejectedValue(new Error('Turn is running')))
  await act(async () => { fireEvent.click(screen.getByRole('menuitem', { name: 'No workspace' })) })
  expect(await screen.findByRole('alert')).toHaveTextContent('Turn is running')
  expect(screen.getByText('Learning algebra')).toBeInTheDocument()
})

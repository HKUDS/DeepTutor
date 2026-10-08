import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import TaskBoardRuntime from '@/components/tasks/TaskBoardRuntime'
import TaskLinkSelector from '@/components/tasks/TaskLinkSelector'
import TaskPanelSection from '@/components/tasks/TaskPanelSection'
import { SessionAvatar } from '@/components/sidebar/SessionAvatar'
import {
  DEFAULT_TASK_COLORS,
  publishTaskBoard,
  sessionTaskColor,
  type TaskBoard,
} from '@/lib/task-board-api'
import translations from '@/locales/en/app.json'
import OrganizedSessionList from '@/components/courses/OrganizedSessionList'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => (translations as Record<string, string>)[key] ?? key,
    i18n: { language: 'en' },
  }),
}))
let board: TaskBoard
let source: { onmessage?: (event: { data: string }) => void; close: ReturnType<typeof vi.fn> }
beforeEach(() => {
  window.history.replaceState({}, '', '/chat/chat?dt_workspace=study')
  board = {
    cards: [
      {
        id: 'one',
        title: 'First task',
        note: 'First note',
        status: 'todo',
        archived: false,
        workspace_id: null,
        created_at: '',
        updated_at: '',
      },
      {
        id: 'two',
        title: 'Second task',
        note: '',
        status: 'done',
        archived: false,
        workspace_id: null,
        created_at: '',
        updated_at: '',
      },
      {
        id: 'workspace',
        title: 'Shared workspace task',
        note: '',
        status: 'doing',
        archived: false,
        workspace_id: 'study',
        created_at: '',
        updated_at: '',
      },
    ],
    colors: { ...DEFAULT_TASK_COLORS },
    session_links: [],
    revision: 1,
  }
  vi.stubGlobal(
    'EventSource',
    class {
      onmessage?: (event: { data: string }) => void
      close = vi.fn()
      constructor() {
        source = this
      }
    }
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = new URL(input, window.location.origin).pathname
      if (init?.method === 'PUT') {
        const payload = JSON.parse(String(init.body))
        board.session_links = [
          {
            session_id: 'chat',
            workspace_id: payload.workspace_id,
            task_ids: payload.task_ids,
            status_link_enabled: true,
          },
        ]
        board.revision++
      } else if (init?.method === 'PATCH' && path.endsWith('/status')) {
        board.session_links[0].status_link_enabled = JSON.parse(String(init.body)).enabled
        board.revision++
      } else if (init?.method === 'PATCH') {
        Object.assign(
          board.cards.find(card => path.endsWith(card.id))!,
          JSON.parse(String(init.body))
        )
        board.revision++
      }
      return Response.json(board)
    })
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
})
function show(mark: 'idle' | 'running' = 'idle') {
  return render(
    <TaskBoardRuntime>
      <TaskLinkSelector sessionId="chat" workspaceId="study" />
      <TaskPanelSection sessionId="chat" />
      <SessionAvatar sessionId="chat" workspaceId="study" mark={mark} />
    </TaskBoardRuntime>
  )
}
function color(view: ReturnType<typeof render>) {
  return view.container.querySelector('svg circle')?.closest('svg')?.style.color
}

describe('task conversation integration', () => {
  it('links multiple tasks, shows them separately and follows the latest task in streamed updates', async () => {
    const view = show()
    await screen.findByRole('combobox', { name: 'Shared workspace task: Task status' })
    const first = await screen.findByRole('checkbox', { name: /First task/ })
    fireEvent.click(first)
    await screen.findByRole('combobox', { name: 'First task: Task status' })
    expect(color(view)).toBe('rgb(37, 99, 235)')
    fireEvent.click(screen.getByRole('checkbox', { name: /Second task/ }))
    await screen.findByRole('combobox', { name: 'Second task: Task status' })
    expect(color(view)).toBe('rgb(21, 128, 61)')
    await act(async () => {
      board.cards[1].status = 'doing'
      board.colors.doing = '#112233'
      board.revision++
      source.onmessage?.({ data: JSON.stringify(board) })
    })
    expect(color(view)).toBe('rgb(17, 34, 51)')
    expect(screen.getByRole('combobox', { name: 'Second task: Task status' })).toHaveValue('doing')
    fireEvent.click(screen.getByRole('button', { name: 'Second task: Unlink task' }))
    await waitFor(() =>
      expect(
        screen.queryByRole('combobox', { name: 'Second task: Task status' })
      ).not.toBeInTheDocument()
    )
    expect(color(view)).toBe('rgb(37, 99, 235)')
  })
  it('lets the sidebar menu stop status sync without removing the task references', async () => {
    board.session_links = [
      { session_id: 'chat', workspace_id: 'study', task_ids: ['one'], status_link_enabled: true },
    ]
    render(
      <TaskBoardRuntime>
        <OrganizedSessionList
          sessions={[
            {
              id: 'chat',
              session_id: 'chat',
              title: 'Study chat',
              created_at: 1,
              updated_at: 1,
              message_count: 0,
              last_message: '',
              content_workspace_id: 'study',
            },
          ]}
          courses={[]}
          activeSessionId="chat"
          onSelect={vi.fn()}
          onRename={vi.fn()}
          onDelete={vi.fn()}
          onOrganize={vi.fn()}
        />
        <TaskPanelSection sessionId="chat" />
      </TaskBoardRuntime>
    )
    await screen.findByRole('combobox', { name: 'First task: Task status' })
    fireEvent.click(screen.getByRole('button', { name: 'Conversation actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Unlink task status' }))
    await waitFor(() => expect(board.session_links[0].status_link_enabled).toBe(false))
    expect(screen.getByRole('combobox', { name: 'First task: Task status' })).toBeInTheDocument()
    expect(sessionTaskColor(board, 'chat', 'study')).toBeUndefined()
  })
  it('preserves the live orb while running, ignores stale responses and closes the stream', async () => {
    board.session_links = [
      { session_id: 'chat', workspace_id: 'study', task_ids: ['one'], status_link_enabled: true },
    ]
    const view = show('running')
    await screen.findByRole('combobox', { name: 'First task: Task status' })
    expect(color(view)).toBe('')
    const latest = structuredClone(board)
    latest.revision = 5
    latest.cards[0].status = 'done'
    await act(async () => {
      source.onmessage?.({ data: JSON.stringify(latest) })
      publishTaskBoard({ ...board, revision: 2 })
    })
    expect(screen.getByRole('combobox', { name: 'First task: Task status' })).toHaveValue('done')
    view.unmount()
    expect(source.close).toHaveBeenCalledOnce()
  })
  it('keeps draft associations local until the conversation exists', async () => {
    const onDraftChange = vi.fn()
    render(
      <TaskBoardRuntime>
        <TaskLinkSelector workspaceId="study" draftTaskIds={[]} onDraftChange={onDraftChange} />
      </TaskBoardRuntime>
    )
    fireEvent.click(await screen.findByRole('checkbox', { name: /First task/ }))
    expect(onDraftChange).toHaveBeenCalledWith(['one'])
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => !init?.method)).toBe(true)
  })
})

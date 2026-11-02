import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import TaskBoardRuntime from '@/components/tasks/TaskBoardRuntime'
import TaskPanelSection from '@/components/tasks/TaskPanelSection'
import KanbanBoard from '@/features/tasks/components/KanbanBoard'
import { DEFAULT_TASK_COLORS, updateTaskCard, type TaskBoard } from '@/lib/task-board-api'
import { useTaskBoard } from '@/lib/task-board-store'
import translations from '@/locales/en/app.json'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => (translations as Record<string, string>)[key] ?? key,
  }),
}))

function board(workspace: string | null, title: string, revision: number): TaskBoard {
  return {
    cards: [{ id: title, title, note: '', due_date: null, status: 'todo', archived: false,
      workspace_id: workspace, created_at: '', updated_at: '' }],
    colors: DEFAULT_TASK_COLORS, session_links: [], revision,
  }
}
function Inspector() {
  const { board } = useTaskBoard()
  return <output data-testid="cards">{board?.cards.map(card => card.title).join(',')}</output>
}
function select(workspace: string) {
  window.history.replaceState({}, '', `/kanban?dt_workspace=${workspace}`)
}
function deferredResponse() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>(done => { resolve = done })
  return { promise, resolve }
}
beforeEach(() => { vi.stubGlobal('EventSource', undefined) })
afterEach(() => { vi.unstubAllGlobals(); select('') })

it('shows legacy General cards in both the board and activity panel and synchronizes edits', async () => {
  select('')
  const current = board(null, 'Legacy task', 1)
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    expect(new URL(input, window.location.origin).searchParams.get('dt_workspace')).toBe('')
    if (init?.method === 'PATCH') {
      Object.assign(current.cards[0], JSON.parse(String(init.body)))
      current.revision++
    }
    return Response.json(current)
  }))
  render(<TaskBoardRuntime><KanbanBoard/><TaskPanelSection sessionId="chat"/></TaskBoardRuntime>)
  await screen.findByRole('button', { name: 'Legacy task' })
  const status = await screen.findByRole('combobox', { name: 'Legacy task: Task status' })
  fireEvent.change(status, { target: { value: 'doing' } })
  await waitFor(() => expect(screen.getByRole('region', { name: 'In progress' })).toHaveTextContent('Legacy task'))
  expect(screen.getByRole('region', { name: 'To do' })).not.toHaveTextContent('Legacy task')
})

it('ignores a previous workspace mutation even when its revision is newer', async () => {
  select('a')
  const pending = deferredResponse()
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const workspace = new URL(input, window.location.origin).searchParams.get('dt_workspace')!
    if (init?.method === 'PATCH') {
      expect(workspace).toBe('a')
      return pending.promise
    }
    return Response.json(board(workspace, workspace === 'a' ? 'A task' : 'B task', 1))
  }))
  const first = render(<TaskBoardRuntime><Inspector/></TaskBoardRuntime>)
  await waitFor(() => expect(screen.getByTestId('cards')).toHaveTextContent('A task'))
  const mutation = updateTaskCard('A task', { status: 'done' })
  first.unmount()
  select('b')
  render(<TaskBoardRuntime><Inspector/></TaskBoardRuntime>)
  await waitFor(() => expect(screen.getByTestId('cards')).toHaveTextContent('B task'))
  await act(async () => {
    pending.resolve(Response.json(board('a', 'A task', 3)))
    await mutation
  })
  expect(screen.getByTestId('cards')).toHaveTextContent('B task')
  expect(screen.getByTestId('cards')).not.toHaveTextContent('A task')
})

it('ignores a previous workspace GET resolved after the new workspace loads', async () => {
  select('a')
  const pending = deferredResponse()
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const workspace = new URL(input, window.location.origin).searchParams.get('dt_workspace')!
    return workspace === 'a' ? pending.promise : Response.json(board('b', 'B task', 1))
  }))
  const first = render(<TaskBoardRuntime><Inspector/></TaskBoardRuntime>)
  first.unmount()
  select('b')
  render(<TaskBoardRuntime><Inspector/></TaskBoardRuntime>)
  await waitFor(() => expect(screen.getByTestId('cards')).toHaveTextContent('B task'))
  await act(async () => { pending.resolve(Response.json(board('a', 'A task', 3))) })
  expect(screen.getByTestId('cards')).toHaveTextContent('B task')
})

it('ignores queued events from a closed workspace stream and accepts the current stream', async () => {
  const streams: Array<{ onmessage?: (event: { data: string }) => void; close: () => void }> = []
  vi.stubGlobal('EventSource', class {
    onmessage?: (event: { data: string }) => void
    close = vi.fn()
    constructor() { streams.push(this) }
  })
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const workspace = new URL(input, window.location.origin).searchParams.get('dt_workspace')!
    return Response.json(board(workspace, workspace === 'a' ? 'A task' : 'B task', 1))
  }))
  select('a')
  const first = render(<TaskBoardRuntime><Inspector/></TaskBoardRuntime>)
  await waitFor(() => expect(screen.getByTestId('cards')).toHaveTextContent('A task'))
  first.unmount()
  expect(streams[0].close).toHaveBeenCalledOnce()
  select('b')
  render(<TaskBoardRuntime><Inspector/></TaskBoardRuntime>)
  await waitFor(() => expect(screen.getByTestId('cards')).toHaveTextContent('B task'))
  await act(async () => { streams[0].onmessage?.({ data: JSON.stringify(board('a', 'A task', 9)) }) })
  expect(screen.getByTestId('cards')).toHaveTextContent('B task')
  await act(async () => { streams[1].onmessage?.({ data: JSON.stringify(board('b', 'Updated B task', 2)) }) })
  expect(screen.getByTestId('cards')).toHaveTextContent('Updated B task')
})

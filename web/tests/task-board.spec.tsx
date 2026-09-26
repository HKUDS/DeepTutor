import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import KanbanPage from '@/app/(workspace)/kanban/page'
import type { TaskBoard } from '@/lib/task-board-api'
import translations from '@/locales/en/app.json'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => (translations as Record<string, string>)[key] ?? key,
  }),
}))

let board: TaskBoard
let failSave: boolean

beforeEach(() => {
  board = { cards: [] }
  failSave = false
  window.history.replaceState({}, '', '/kanban?dt_workspace=study')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, window.location.origin)
      expect(url.searchParams.get('dt_workspace')).toBe('study')
      expect(init?.credentials).toBe('include')
      if (init?.method === 'POST') {
        if (failSave) return Response.json({}, { status: 500 })
        const payload = JSON.parse(String(init.body))
        board.cards.push({
          id: 'task-1',
          title: payload.title,
          note: '',
          status: 'todo',
          archived: false,
          created_at: '2026-01-01',
          updated_at: '2026-01-01',
        })
      } else if (init?.method === 'PATCH') {
        if (failSave) return Response.json({}, { status: 500 })
        board.cards[0] = { ...board.cards[0], ...JSON.parse(String(init.body)) }
      }
      return Response.json(board)
    })
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
})

async function addTask() {
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'New task' })).toBeEnabled())
  fireEvent.change(screen.getByRole('textbox', { name: 'New task' }), {
    target: { value: 'Review derivatives' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Add' }))
  await screen.findByRole('button', { name: 'Review derivatives' })
}

describe('Task Board', () => {
  it('creates, edits, moves, archives and restores cards through the scoped API', async () => {
    render(<KanbanPage />)
    await addTask()
    fireEvent.click(screen.getByRole('button', { name: 'Review derivatives' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Task note' }), {
      target: { value: 'Three examples' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByText('Three examples')
    fireEvent.click(screen.getByRole('button', { name: 'Review derivatives: Move to In progress' }))
    await waitFor(() =>
      expect(
        within(screen.getByRole('region', { name: 'In progress' })).getByText('Review derivatives')
      ).toBeInTheDocument()
    )
    fireEvent.click(screen.getByRole('button', { name: 'Review derivatives: Archive' }))
    await waitFor(() => expect(screen.queryByText('Review derivatives')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Show archived' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Review derivatives: Restore' }))
    await waitFor(() => expect(screen.queryByText('Review derivatives')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Show active' }))
    expect(
      within(screen.getByRole('region', { name: 'In progress' })).getByText('Review derivatives')
    ).toBeInTheDocument()
    expect(screen.getByText('Three examples')).toBeInTheDocument()
  })

  it('moves a dragged card and reads it again after remounting', async () => {
    const view = render(<KanbanPage />)
    await addTask()
    const dataTransfer = { setData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(screen.getByRole('article'), { dataTransfer })
    fireEvent.drop(screen.getByRole('region', { name: 'Done' }), { dataTransfer })
    await waitFor(() =>
      expect(
        within(screen.getByRole('region', { name: 'Done' })).getByText('Review derivatives')
      ).toBeInTheDocument()
    )
    view.unmount()
    render(<KanbanPage />)
    await waitFor(() =>
      expect(
        within(screen.getByRole('region', { name: 'Done' })).getByText('Review derivatives')
      ).toBeInTheDocument()
    )
  })

  it('keeps the draft and existing card when saving fails', async () => {
    render(<KanbanPage />)
    await addTask()
    fireEvent.click(screen.getByRole('button', { name: 'Review derivatives' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Task note' }), {
      target: { value: 'Unsaved note' },
    })
    failSave = true
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save the card.')
    expect(screen.getByRole('textbox', { name: 'Task note' })).toHaveValue('Unsaved note')
    expect(board.cards[0].note).toBe('')
  })

  it('disables creation during loading and lets a failed load retry', async () => {
    let rejectLoad!: (error: Error) => void
    vi.mocked(fetch).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectLoad = reject
        })
    )
    render(<KanbanPage />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading task board')
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
    await act(async () => rejectLoad(new Error('Offline')))
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'New task' })).toBeEnabled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

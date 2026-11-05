import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import NotebookConsole from '@/components/notebook/NotebookConsole'
import NoteFavoritesPicker from '@/features/notes/components/NoteFavoritesPicker'
import { favoriteRecordRoute } from '@/lib/resource-routes'

const mocks = vi.hoisted(() => ({
  router: { push: vi.fn(), replace: vi.fn() },
  locate: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  collection: {
    id: 'inbox',
    name: 'Inbox',
    records: [
      {
        id: 'a',
        title: 'Alpha',
        output: '**Original**',
        summary: 'Saved source',
        type: 'chat',
        user_query: '',
      },
      { id: 'b', title: 'Beta', output: 'Other body', summary: '', type: 'chat', user_query: '' },
    ],
  },
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate }) }))
function translate(key: string) {
  return key
}
vi.mock('@/components/common/PickerShell', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div role="dialog">{children}</div>,
}))
vi.mock('next/navigation', () => ({ useRouter: () => mocks.router }))
vi.mock('@/components/notebook/NotebookRecordRow', () => ({
  default: ({
    record,
    expanded,
    onToggle,
  }: {
    record: { id: string; title: string }
    expanded: boolean
    onToggle: () => void
  }) => (
    <button aria-expanded={expanded} onClick={onToggle}>
      {record.title}
    </button>
  ),
}))
vi.mock('@/lib/notebook-api', () => ({
  locateFavoriteRecord: (...args: unknown[]) => mocks.locate(...args),
  listNotebooks: () => mocks.list(),
  getNotebook: (id: string) => mocks.get(id),
}))
vi.mock('@/components/notebook/useNotebookLibrary', () => ({
  useNotebookLibrary: () => ({
    selectedId: 'inbox',
    selected: mocks.collection,
    notebooks: [mocks.collection],
    loading: false,
    detailLoading: false,
    select: vi.fn(),
  }),
}))

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
  mocks.locate.mockResolvedValue(null)
  mocks.list.mockResolvedValue([mocks.collection])
  mocks.get.mockResolvedValue(mocks.collection)
})
it('encodes source identities without losing the target record', () => {
  expect(favoriteRecordRoute('folder / 一', 'r? 1')).toBe(
    '/notebooks/folder%20%2F%20%E4%B8%80?record=r%3F%201'
  )
})
it('opens the exact source and keeps it visible even with a previous filter', async () => {
  render(<NotebookConsole initialNotebookId="inbox" initialRecordId="b" />)
  expect(screen.getByRole('button', { name: 'Beta' })).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-expanded', 'false')
  fireEvent.change(screen.getByPlaceholderText('Search records in this notebook'), {
    target: { value: 'unmatched' },
  })
  expect(screen.getByRole('button', { name: 'Beta' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Beta' }))
  expect(mocks.router.replace).toHaveBeenCalledWith('/notebooks/inbox', { scroll: false })
  expect(mocks.locate).not.toHaveBeenCalled()
})
it('expands and collapses in place while keeping the record in the URL', () => {
  const { rerender } = render(<NotebookConsole initialNotebookId="inbox" />)
  fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
  expect(mocks.router.replace).toHaveBeenLastCalledWith('/notebooks/inbox?record=a', {
    scroll: false,
  })
  rerender(<NotebookConsole initialNotebookId="inbox" initialRecordId="a" />)
  expect(screen.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-expanded', 'true')
  expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: 'Beta' }))
  rerender(<NotebookConsole initialNotebookId="inbox" initialRecordId="b" />)
  expect(screen.getByRole('button', { name: 'Beta' })).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-expanded', 'false')
  expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: 'Beta' }))
  expect(mocks.router.replace).toHaveBeenLastCalledWith('/notebooks/inbox', { scroll: false })
  rerender(<NotebookConsole initialNotebookId="inbox" />)
  expect(screen.getByRole('button', { name: 'Beta' })).toHaveAttribute('aria-expanded', 'false')
  expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
})
it('locates incoming source links once, including navigation after a local toggle', () => {
  const { rerender } = render(<NotebookConsole initialNotebookId="inbox" initialRecordId="b" />)
  expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1)

  const collection = mocks.collection
  mocks.collection = { ...collection }
  rerender(<NotebookConsole initialNotebookId="inbox" initialRecordId="b" />)
  expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1)
  mocks.collection = collection

  fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
  rerender(<NotebookConsole initialNotebookId="inbox" initialRecordId="a" />)
  expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1)

  rerender(<NotebookConsole initialNotebookId="inbox" initialRecordId="b" />)
  expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(2)
  expect(screen.getByRole('button', { name: 'Beta' })).toHaveAttribute('aria-expanded', 'true')
})
it('redirects an old source link after moving the favorite', async () => {
  mocks.locate.mockResolvedValue('archive')
  render(<NotebookConsole initialNotebookId="inbox" initialRecordId="moved" />)
  await waitFor(() =>
    expect(mocks.router.replace).toHaveBeenCalledWith('/notebooks/archive?record=moved')
  )
})
it('shows a missing-source notice instead of opening a different favorite', async () => {
  render(<NotebookConsole initialNotebookId="inbox" initialRecordId="deleted" />)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'This favorite is no longer available.'
  )
  expect(screen.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-expanded', 'false')
})
it('inserts original text with its exact source link and closes the picker', async () => {
  const insert = vi.fn(),
    close = vi.fn()
  render(<NoteFavoritesPicker onInsert={insert} onClose={close} onSynthesize={vi.fn()} />)
  fireEvent.click(await screen.findByRole('checkbox', { name: /Alpha.*Saved source/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Insert' }))
  expect(insert).toHaveBeenCalledWith([
    {
      title: 'Alpha',
      markdown: '**Original**',
      sourceUrl: '/notebooks/inbox?record=a',
      sourceId: 'a',
      favorite: {
        type: 'chat',
        summary: 'Saved source',
        metadata: { favorite_collection: 'Inbox' },
      },
    },
  ])
  expect(close).toHaveBeenCalledOnce()
})
it('inserts a filtered multi-selection as one batch in the order it was picked', async () => {
  const insert = vi.fn()
  render(<NoteFavoritesPicker onInsert={insert} onClose={vi.fn()} onSynthesize={vi.fn()} />)
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Beta' }))
  fireEvent.change(screen.getByLabelText('Search favorites'), { target: { value: 'Alpha' } })
  expect(screen.queryByRole('checkbox', { name: 'Beta' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('checkbox', { name: /Alpha.*Saved source/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Insert {{count}}' }))
  expect(insert).toHaveBeenCalledOnce()
  expect(insert.mock.calls[0][0].map((clip: { sourceId: string }) => clip.sourceId)).toEqual([
    'b',
    'a',
  ])
})
it('browses one collection at a time and shows its empty state', async () => {
  mocks.list.mockResolvedValue([mocks.collection, { id: 'empty', name: 'Empty' }])
  mocks.get.mockImplementation((id: string) =>
    Promise.resolve(id === 'empty' ? { records: [] } : mocks.collection)
  )
  render(<NoteFavoritesPicker onInsert={vi.fn()} onClose={vi.fn()} onSynthesize={vi.fn()} />)
  await screen.findByRole('checkbox', { name: /Alpha.*Saved source/ })
  fireEvent.click(screen.getByRole('button', { name: /^Empty/ }))
  await waitFor(() =>
    expect(screen.getByText('No favorites in this collection yet.')).toBeVisible()
  )
  expect(screen.getByRole('button', { name: 'Insert' })).toBeDisabled()
})

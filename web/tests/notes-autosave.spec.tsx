import { useEffect } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import NoteWorkspace from '@/features/notes/components/NoteWorkspace'
import { loadDestination } from '@/features/notes/components/note-page-mutations'
import { prepareNoteDestination } from '@/features/notes/components/useNoteNavigation'
import * as coWriter from '@/lib/co-writer-api'
import {
  getNote,
  listNotes,
  saveNote,
  getSuggestions,
  noteRequest,
  reviewSuggestion,
} from '@/lib/notes-api'
import type { NotePage, NoteSuggestion } from '@/lib/notes-api'
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock('next/navigation', () => ({ useRouter: () => router }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/hooks/useAuthStatus', () => ({
  useAuthStatus: () => ({ statusAvailable: true, loading: false, enabled: false }),
}))
vi.mock('@/lib/notes-api', () => ({
  getNote: vi.fn(),
  listNotes: vi.fn(),
  saveNote: vi.fn(),
  getSuggestions: vi.fn(),
  noteRequest: vi.fn(),
  reviewSuggestion: vi.fn(),
  exportNoteFlashcards: vi.fn(),
}))
// The page's conversations run in the chat runtime; autosave does not.
vi.mock('@/features/notes/components/useNoteThreads', () => ({
  useNoteThreads: () => ({
    threads: [],
    open: null,
    bound: false,
    hasMessages: false,
    prefill: null,
    send: vi.fn(),
    openThread: vi.fn(),
    startThread: vi.fn(),
    generateBlock: vi.fn(),
    regenerate: vi.fn(),
    removeThread: vi.fn(),
    close: vi.fn(),
  }),
}))
vi.mock('@/features/notes/components/NoteEditor', () => ({
  default: function MockEditor({
    onReady,
    onChange,
    page,
    suggestions,
    onReview,
    reviewErrors,
  }: {
    onReady: (value: unknown) => void
    onChange: (value: NotePage['blocks']) => void
    page: NotePage
    suggestions: NoteSuggestion[]
    onReview: (suggestion: NoteSuggestion, accept: boolean) => void
    reviewErrors: Record<string, string>
  }) {
    useEffect(() => {
      onReady({ setEditable: vi.fn(), replace: vi.fn() })
    }, [])
    return (
      <div>
        Editor{' '}
        <button
          onClick={() =>
            onChange([{ id: 'edited', type: 'paragraph', props: {}, content: 'New content' }])
          }
        >
          Edit block
        </button>
        <output data-testid="editor-snapshot">{JSON.stringify(page.blocks)}</output>
        {suggestions.map(s => (
          <section key={s.id}>
            <button onClick={() => onReview(s, true)}>Accept {s.id}</button>
            <button onClick={() => onReview(s, false)}>Dismiss {s.id}</button>
            {reviewErrors[s.id] && <p role="alert">{reviewErrors[s.id]}</p>}
          </section>
        ))}
      </div>
    )
  },
}))
const page: NotePage = {
  id: 'abcdef123456',
  title: 'Initial',
  content: 'Body',
  blocks: [{ id: 'a', type: 'paragraph', props: {}, content: 'Body' }],
  parent_id: null,
  icon: '',
  cover: '',
  pinned: false,
  revision: 1,
  created_at: 1,
  updated_at: 1,
}
beforeEach(() => {
  localStorage.clear()
  vi.mocked(getNote).mockResolvedValue({ ...page })
  vi.mocked(listNotes).mockResolvedValue({ documents: [{ ...page, preview: 'Body' }] })
  vi.mocked(getSuggestions).mockResolvedValue({ suggestions: [] })
  vi.mocked(noteRequest).mockResolvedValue({ pages: [] })
})

const proposal: NoteSuggestion = {
  id: 's1',
  operation: 'replace',
  block_id: 'a',
  markdown: '',
  explanation: '',
  original: page.blocks![0],
  blocks: [{ ...page.blocks![0], content: 'Accepted' }],
  status: 'pending',
}
it.each([true, false])('resolves the parent draft before mounting the return editor (matching revision: %s)', async matches => {
  const child = { ...page, id: '123456abcdef', parent_id: page.id }
  const blocks = [{ ...page.blocks![0], content: 'Recovered draft body' }]
  localStorage.setItem(`deeptutor.notes.draft:local:${page.id}`, JSON.stringify({
    blocks, title: 'Draft title', revision: matches ? page.revision : page.revision - 1,
  }))
  const destination = await loadDestination(child, [], true, '', 'local')
  // BlockNote consumes its initial blocks once on mount.
  expect(destination.doc?.blocks).toEqual(matches ? blocks : page.blocks)
  prepareNoteDestination(destination)
  vi.mocked(saveNote).mockResolvedValue({ ...page, revision: 2 })
  render(<NoteWorkspace docId={page.id} />)
  if (matches) {
    await waitFor(() => expect(saveNote).toHaveBeenCalledWith(page.id, {
      title: 'Draft title', blocks, expected_revision: page.revision,
    }))
  } else {
    expect(await screen.findByText('A local draft differs from this page.')).toBeInTheDocument()
    expect(saveNote).not.toHaveBeenCalled()
  }
})

it('deletes the selected child while preserving unsaved edits on its same-named parent', async () => {
  const parent = { ...page, preview: 'Body' }
  const child = { ...parent, parent_id: parent.id, id: '123456abcdef' }
  vi.mocked(listNotes)
    .mockResolvedValueOnce({ documents: [parent, child] })
    .mockResolvedValue({ documents: [parent] })
  vi.mocked(saveNote).mockResolvedValue({ ...page, revision: 2 })
  const remove = vi.spyOn(coWriter, 'deleteCoWriterDocument').mockResolvedValue(true)
  render(<NoteWorkspace docId={parent.id} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Edit block' }))
  fireEvent.click(screen.getByRole('button', { name: 'Page tree' }))
  const row = screen.getAllByRole('link', { name: parent.title })
    .find(link => link.getAttribute('href') === `/co-writer/${child.id}`)!
  fireEvent.contextMenu(row)
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Delete page' }))
  await waitFor(() => expect(remove).toHaveBeenCalledWith(child.id))
  expect(saveNote).toHaveBeenCalledWith(parent.id, expect.objectContaining({ expected_revision: 1 }))
  expect(screen.getByTestId('editor-snapshot')).toHaveTextContent('New content')
  expect(router.replace).not.toHaveBeenCalled()
  expect(router.push).not.toHaveBeenCalled()
})

it('flushes a newly typed edit before approval and retains the returned content on remount', async () => {
  let finish!: (value: NotePage) => void
  vi.mocked(getSuggestions).mockResolvedValue({ suggestions: [proposal] })
  vi.mocked(saveNote).mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const accepted = {
    ...page,
    blocks: [
      ...proposal.blocks!,
      { id: 'edited', type: 'paragraph', props: {}, content: 'New content' },
    ],
    revision: 3,
  }
  vi.mocked(reviewSuggestion).mockResolvedValue(accepted)
  const ui = render(<NoteWorkspace docId={page.id} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Edit block' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Accept s1' }))
  await waitFor(() => expect(saveNote).toHaveBeenCalledTimes(1))
  expect(reviewSuggestion).not.toHaveBeenCalled()
  finish({ ...page, revision: 2 })
  await waitFor(() =>
    expect(reviewSuggestion).toHaveBeenCalledWith(page.id, 's1', true, proposal.blocks)
  )
  expect(screen.getByTestId('editor-snapshot')).toHaveTextContent('Accepted')
  expect(screen.getByTestId('editor-snapshot')).toHaveTextContent('New content')
  ui.unmount()
  vi.mocked(getNote).mockResolvedValue(accepted)
  vi.mocked(getSuggestions).mockResolvedValue({ suggestions: [] })
  render(<NoteWorkspace docId={page.id} />)
  expect(await screen.findByTestId('editor-snapshot')).toHaveTextContent('Accepted')
  expect(screen.getByTestId('editor-snapshot')).toHaveTextContent('New content')
})
it('keeps conflicting edits intact and lets the user dismiss the suggestion locally', async () => {
  vi.mocked(getSuggestions).mockResolvedValue({ suggestions: [proposal] })
  vi.mocked(reviewSuggestion)
    .mockRejectedValueOnce(
      new Error('The suggested block changed. Ask Dito to revise the suggestion.')
    )
    .mockResolvedValueOnce(page)
  render(<NoteWorkspace docId={page.id} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Accept s1' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Your edits are safe')
  expect(screen.getByTestId('editor-snapshot')).toHaveTextContent('Body')
  vi.mocked(getSuggestions).mockResolvedValue({ suggestions: [] })
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss s1' }))
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Accept s1' })).not.toBeInTheDocument()
  )
  expect(reviewSuggestion).toHaveBeenLastCalledWith(page.id, 's1', false, undefined)
  expect(screen.getByTestId('editor-snapshot')).toHaveTextContent('Body')
})
it('passes current blocks back to the editor so remounts cannot restore stale content', async () => {
  vi.mocked(saveNote).mockResolvedValue({ ...page, revision: 2 })
  render(<NoteWorkspace docId={page.id} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Edit block' }))
  expect(screen.getByTestId('editor-snapshot')).toHaveTextContent('New content')
  await waitFor(() => expect(saveNote).toHaveBeenCalledTimes(1), { timeout: 3000 })
  expect(vi.mocked(saveNote).mock.calls[0][1].blocks?.[0].id).toBe('edited')
  expect(screen.getByTestId('editor-snapshot')).toHaveTextContent('New content')
})
it('serializes edits made during an in-flight save against the returned revision', async () => {
  let finish!: (value: NotePage) => void
  vi.mocked(saveNote)
    .mockImplementationOnce(
      () =>
        new Promise(resolve => {
          finish = resolve
        })
    )
    .mockResolvedValueOnce({ ...page, title: 'Second', revision: 3 })
  render(<NoteWorkspace docId={page.id} />)
  const title = await screen.findByRole('textbox', { name: 'Page title' })
  fireEvent.change(title, { target: { value: 'First' } })
  await waitFor(() => expect(saveNote).toHaveBeenCalledTimes(1), { timeout: 3000 })
  fireEvent.change(title, { target: { value: 'Second' } })
  finish({ ...page, title: 'First', revision: 2 })
  await waitFor(() => expect(saveNote).toHaveBeenCalledTimes(2))
  expect(vi.mocked(saveNote).mock.calls[1][1]).toMatchObject({
    title: 'Second',
    expected_revision: 2,
  })
  await waitFor(() => expect(screen.getByText('Saved')).toBeInTheDocument())
  expect(title).toHaveValue('Second')
})
it('keeps a recovery draft on conflict instead of overwriting a newer page', async () => {
  vi.mocked(saveNote).mockRejectedValue(new Error('This page changed elsewhere'))
  render(<NoteWorkspace docId={page.id} />)
  fireEvent.change(await screen.findByRole('textbox', { name: 'Page title' }), {
    target: { value: 'Unsaved' },
  })
  await waitFor(
    () => expect(screen.getByRole('alert')).toHaveTextContent('This page changed elsewhere'),
    { timeout: 3000 }
  )
  expect(localStorage.getItem(`deeptutor.notes.draft:local:${page.id}`)).toContain('Unsaved')
})

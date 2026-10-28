import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AddToNote from '@/features/notes/components/AddToNote'

const mocks = vi.hoisted(() => ({
  get: vi.fn(), save: vi.fn(), request: vi.fn(), parse: vi.fn(),
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/notes-api', () => ({
  listNotes: async () => ({ documents: [{ id: 'legacy', title: 'Legacy page' }] }),
  createNote: vi.fn(), getNote: mocks.get, saveNote: mocks.save, noteRequest: mocks.request,
}))
vi.mock('@/features/notes/components/NoteEditor', () => ({ parseLegacyNoteContent: mocks.parse }))
vi.mock('@/lib/co-writer-events', () => ({ notifyCoWriterChanged: vi.fn() }))
beforeEach(() => {
  mocks.get.mockResolvedValue({ id: 'legacy', blocks: null, content: '# Keep me', revision: 7 })
  mocks.parse.mockReturnValue([{ id: 'old', type: 'heading', content: 'Keep me' }])
  mocks.save.mockResolvedValue({})
  mocks.request.mockResolvedValue({})
})
async function insert() {
  render(<AddToNote title="Favorite" markdown="Original" sourceUrl="/notebooks/inbox?record=r" sourceId="r" favorite={{ type: 'research', summary: 'Summary', metadata: { source: 'research' } }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Add to a note' }))
  await screen.findByRole('option', { name: 'Legacy page' })
  fireEvent.change(screen.getByRole('combobox', { name: 'Target page' }), { target: { value: 'legacy' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add to a note' }))
}
it('migrates legacy text with revision protection before appending a typed source block', async () => {
  await insert()
  await screen.findByRole('link', { name: 'Open note' })
  expect(mocks.parse).toHaveBeenCalledWith('# Keep me')
  expect(mocks.save).toHaveBeenCalledWith('legacy', { blocks: [{ id: 'old', type: 'heading', content: 'Keep me' }], expected_revision: 7 })
  expect(mocks.request).toHaveBeenCalledWith('/legacy/clips', expect.objectContaining({ favorite_type: 'research', source_id: 'r', markdown: 'Original', favorite_metadata: { source: 'research' } }))
  expect(mocks.save.mock.invocationCallOrder[0]).toBeLessThan(mocks.request.mock.invocationCallOrder[0])
})
it('does not append to or overwrite a page that changed during legacy migration', async () => {
  mocks.save.mockRejectedValue(new Error('Page changed; reopen it first'))
  await insert()
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Page changed'))
  expect(mocks.request).not.toHaveBeenCalled()
  expect(screen.queryByRole('link', { name: 'Open note' })).not.toBeInTheDocument()
})

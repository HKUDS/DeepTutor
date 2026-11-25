import { act, render, renderHook, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useNoteImport } from '@/features/notes/components/useNoteImport'
import { useNoteDestination } from '@/features/notes/components/useNoteNavigation'
import { importNoteDocument } from '@/features/notes/model/import-document'
import type { NotePage } from '@/lib/notes-api'

const push = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/features/notes/model/import-document', () => ({ importNoteDocument: vi.fn() }))
vi.mock('@/features/notes/components/NoteEditor', () => ({ default: () => null }))

const doc: NotePage = {
  id: 'ab1234567890',
  title: 'Lecture',
  content: 'Body',
  blocks: [],
  revision: 0,
  created_at: 1,
  updated_at: 1,
  parent_id: null,
  icon: '',
  cover: '',
  pinned: false,
}
const file = new File(['Body'], 'Lecture.md')

it('hands the creation response to the first render only and skips progress for a quick import', async () => {
  vi.mocked(importNoteDocument).mockResolvedValue(doc)
  const importer = renderHook(() => useNoteImport([], vi.fn(), true))
  await act(() => importer.result.current.openFile(file))
  expect(importer.result.current.dialog).toBeFalsy()
  expect(push).toHaveBeenCalledWith(expect.stringContaining(doc.id))
  const destination = renderHook(() => useNoteDestination(doc.id))
  expect(destination.result.current).toMatchObject({ doc, treeOpen: true })
  destination.unmount()
  expect(renderHook(() => useNoteDestination(doc.id)).result.current).toBeNull()
})

it('shows delayed progress during a pending import and clears it on failure', async () => {
  vi.useFakeTimers()
  try {
    let fail!: (error: Error) => void
    vi.mocked(importNoteDocument).mockImplementation(
      () =>
        new Promise((_, reject) => {
          fail = reject
        })
    )
    const onError = vi.fn()
    const importer = renderHook(() => useNoteImport([], onError))
    let operation!: Promise<void>
    await act(async () => {
      operation = importer.result.current.openFile(file)
    })
    act(() => vi.advanceTimersByTime(499))
    expect(importer.result.current.dialog).toBeFalsy()
    act(() => vi.advanceTimersByTime(1))
    const modal = render(<>{importer.result.current.dialog}</>)
    expect(screen.getByRole('dialog')).toHaveTextContent(file.name)
    await act(async () => {
      fail(new Error('Import failed'))
      await operation
      expect(onError).toHaveBeenCalledWith('Import failed')
    })
    modal.rerender(<>{importer.result.current.dialog}</>)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(importer.result.current.importing).toBe(false)
  } finally {
    vi.useRealTimers()
  }
})

import { act, render, renderHook, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useNoteImport } from '@/features/notes/components/useNoteImport'
import { useNoteDestination } from '@/features/notes/components/useNoteNavigation'
import { importNoteDocument } from '@/features/notes/model/import-document'
import { noteRequest, type NotePage } from '@/lib/notes-api'
import { loadPdfjs } from '@/lib/pdfjs-loader'

const push = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/lib/notes-api', () => ({ noteRequest: vi.fn() }))
vi.mock('@/lib/pdfjs-loader', () => ({
  loadPdfjs: vi.fn(),
  pdfjsCMapUrl: () => '',
  pdfjsWasmUrl: () => '',
}))

const t = (key: string) => key

it('creates editable headings, lists, links and code from notebook Markdown', async () => {
  const markdown =
    '## Lecture\r\n\r\n- Read [source](https://example.com)\r\n\r\n```js\r\nlet x = 1\r\n```'
  await importNoteDocument(new File([markdown], 'Lecture.md'), t)
  const payload = vi.mocked(noteRequest).mock.calls[0][1]
  expect(payload).toMatchObject({
    title: 'Lecture',
    blocks: [
      { type: 'heading', props: { level: 2 } },
      {
        type: 'bulletListItem',
        content: expect.arrayContaining([
          { type: 'link', href: 'https://example.com', content: expect.any(Array) },
        ]),
      },
      { type: 'codeBlock', content: [expect.objectContaining({ text: 'let x = 1' })] },
    ],
  })
})

function pdfWithPages(pages: string[][]) {
  const document = {
    numPages: pages.length,
    getPage: async (number: number) => ({
      getTextContent: async () => ({
        items: pages[number - 1].map((str, index) => ({
          str,
          transform: [1, 0, 0, 1, 20, 300 - index * 30],
          height: 12,
          hasEOL: true,
        })),
      }),
      cleanup: vi.fn(),
    }),
  }
  vi.mocked(loadPdfjs).mockResolvedValue({
    getDocument: () => ({ promise: Promise.resolve(document), destroy: vi.fn() }),
  } as unknown as Awaited<ReturnType<typeof loadPdfjs>>)
  return new File(['pdf'], '讲义.pdf')
}

it('imports PDF text as ordered paragraphs and skips image-only pages', async () => {
  const report = vi.fn()
  await importNoteDocument(pdfWithPages([['甲', '乙'], [], ['丙']]), t, report)
  expect(report.mock.calls.map(([progress]) => progress)).toEqual([
    { label: 'Processing…', page: 1, pages: 3 },
    { label: 'Processing…', page: 2, pages: 3 },
    { label: 'Processing…', page: 3, pages: 3 },
    { label: 'Saving…' },
  ])
  expect(noteRequest).toHaveBeenCalledWith('', {
    title: '讲义',
    blocks: ['甲', '乙', '丙'].map(text =>
      expect.objectContaining({
        type: 'paragraph',
        content: [{ type: 'text', text, styles: {} }],
      })
    ),
  })
})

it('explains an image-only PDF without creating a note', async () => {
  await expect(importNoteDocument(pdfWithPages([[], []]), t)).rejects.toThrow('OCR')
  expect(noteRequest).not.toHaveBeenCalled()
})

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
  vi.mocked(noteRequest).mockResolvedValue(doc)
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
    vi.mocked(noteRequest).mockImplementation(
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
    vi.useRealTimers()
    const modal = render(<>{importer.result.current.dialog}</>)
    expect(await screen.findByRole('dialog')).toHaveTextContent(file.name)
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

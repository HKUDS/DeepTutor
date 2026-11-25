import { expect, it, vi } from 'vitest'
import { importNoteDocument } from '@/features/notes/model/import-document'
import { noteRequest } from '@/lib/notes-api'
import { loadPdfjs } from '@/lib/pdfjs-loader'

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

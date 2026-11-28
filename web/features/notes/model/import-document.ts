import type { TextItem } from 'pdfjs-dist/types/src/display/api'
import { importCoWriterDocx } from '@/lib/co-writer-api'
import { noteRequest, type NoteBlock, type NotePage } from '@/lib/notes-api'
import { loadPdfjs, pdfjsCMapUrl, pdfjsWasmUrl } from '@/lib/pdfjs-loader'
import { activeWorkspaceId } from '@/lib/workspace-scope'
import { safeNoteUrl } from './urls'

export type ImportProgress = { label: string; page?: number; pages?: number }
type ReportProgress = (progress: ImportProgress) => void

// Local file imports have no base URL. Unwrap unresolved links, keeping their
// styled text. BlockNote also stores inline content in nested blocks and table cells.
function unwrapUnsupportedLinks(blocks: NoteBlock[]) {
  const inline = (items: unknown[]) =>
    items.flatMap(item => {
      const link = item as { type: string; href?: string; content: unknown[] }
      return link.type === 'link' && !safeNoteUrl(link.href) ? link.content : [item]
    })
  for (const block of blocks) {
    if (Array.isArray(block.content)) block.content = inline(block.content)
    if (block.type === 'table') {
      const table = block.content as { rows: { cells: (unknown[] | { content: unknown[] })[] }[] }
      for (const row of table.rows) {
        row.cells = row.cells.map(cell =>
          Array.isArray(cell) ? inline(cell) : { ...cell, content: inline(cell.content) }
        )
      }
    }
    if (block.children) unwrapUnsupportedLinks(block.children)
  }
}

function pdfParagraphs(items: TextItem[]): string[] {
  const paragraphs: string[] = []
  let text = ''
  let previous: TextItem | undefined
  for (const item of items) {
    if (!item.str) continue
    if (previous) {
      const gap = Math.abs(item.transform[5] - previous.transform[5])
      const height = Math.max(previous.height, item.height)
      if (height && gap > height * 1.6) {
        if (text.trim()) paragraphs.push(text.trim())
        text = ''
      } else if (previous.hasEOL || gap > height / 2) {
        text += '\n'
      }
    }
    text += item.str
    previous = item
  }
  if (text.trim()) paragraphs.push(text.trim())
  return paragraphs
}

async function pdfBlocks(file: File, report?: ReportProgress): Promise<NoteBlock[]> {
  const pdfjs = await loadPdfjs()
  const task = pdfjs.getDocument({
    data: await file.arrayBuffer(),
    cMapUrl: pdfjsCMapUrl(),
    cMapPacked: true,
    wasmUrl: pdfjsWasmUrl(),
  })
  const blocks: NoteBlock[] = []
  try {
    const pdf = await task.promise
    for (let number = 1; number <= pdf.numPages; number++) {
      const page = await pdf.getPage(number)
      const { items } = await page.getTextContent()
      for (const text of pdfParagraphs(items.filter((item): item is TextItem => 'str' in item))) {
        blocks.push({
          id: crypto.randomUUID(),
          type: 'paragraph',
          props: {},
          content: [{ type: 'text', text, styles: {} }],
          children: [],
        })
      }
      page.cleanup()
      report?.({ label: 'Processing…', page: number, pages: pdf.numPages })
    }
    return blocks
  } finally {
    await task.destroy()
  }
}

export async function importNoteDocument(
  file: File,
  t: (key: string) => string,
  report?: ReportProgress
) {
  const workspace = activeWorkspaceId()
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (extension === 'docx') {
    report?.({ label: 'Processing…' })
    return importCoWriterDocx(file)
  }
  let blocks: NoteBlock[]
  if (extension === 'pdf') {
    blocks = await pdfBlocks(file, report)
    if (!blocks.length)
      throw new Error(t('No text was found in this PDF. For a scan, run OCR first.'))
  } else if (extension === 'md' || extension === 'markdown') {
    const { parseLegacyNoteContent } = await import('../components/NoteEditor')
    blocks = parseLegacyNoteContent((await file.text()).replace(/\r\n?/g, '\n'))
    unwrapUnsupportedLinks(blocks)
    if (!blocks.length) throw new Error(t('The Markdown file is empty.'))
  } else {
    throw new Error(t('Choose a Word, Markdown or PDF document.'))
  }
  if (workspace !== activeWorkspaceId()) throw new Error(t('Cancelled'))
  report?.({ label: 'Saving…' })
  return noteRequest<NotePage>('', { title: file.name.replace(/\.[^.]+$/, ''), blocks })
}

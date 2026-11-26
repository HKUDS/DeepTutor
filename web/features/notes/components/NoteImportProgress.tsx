'use client'
import { useTranslation } from 'react-i18next'
import { Dialog } from '@/shared/ui/Dialog'
import { activeWorkspaceId, scopedUrl } from '@/lib/workspace-scope'
import { notifyCoWriterChanged } from '@/lib/co-writer-events'
import type { NoteSummary } from '@/lib/notes-api'
import { prepareNoteDestination } from './useNoteNavigation'
import { importNoteDocument, type ImportProgress } from '../model/import-document'

export async function openImportedFile(
  file: File,
  {
    beforeImport,
    report,
    showProgress,
    workspace,
    isMounted,
    pages,
    treeOpen,
    navigate,
    t,
  }: {
    beforeImport?: () => Promise<void>
    report: (value: ImportProgress) => void
    showProgress: () => void
    workspace: string
    isMounted: () => boolean
    pages: NoteSummary[]
    treeOpen: boolean
    navigate: (url: string) => void
    t: (key: string) => string
  }
) {
  await beforeImport?.()
  report({ label: 'Reading file' })
  const { default: Editor } = await import('./NoteEditor')
  // BlockNote parses Markdown synchronously. Paint progress before a large parse
  // gets the main thread, otherwise the delayed dialog cannot appear until it ends.
  if (/\.(md|markdown)$/i.test(file.name) && file.size >= 256 * 1024) {
    showProgress()
    report({ label: 'Processing…' })
    await new Promise<void>(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)))
  }
  if (!isMounted()) return
  if (workspace !== activeWorkspaceId()) throw new Error(t('Cancelled'))
  const doc = await importNoteDocument(file, t, report)
  if (!isMounted()) return
  if (workspace !== activeWorkspaceId()) throw new Error(t('Cancelled'))
  report({ label: 'Opening document…' })
  prepareNoteDestination({
    doc,
    pages: [{ ...doc, preview: '' }, ...pages],
    treeOpen,
    workspace,
    Editor,
  })
  notifyCoWriterChanged()
  navigate(scopedUrl(`/co-writer/${doc.id}`, workspace))
}

export function NoteImportProgress({
  fileName,
  progress,
}: {
  fileName: string
  progress: ImportProgress
}) {
  const { t } = useTranslation()
  const message = progress.pages
    ? t('Page {{page}} of {{pages}}', { page: progress.page, pages: progress.pages })
    : t(progress.label)
  return (
    <Dialog open busy size="sm" title={t('Importing…')} description={fileName} onClose={() => {}}>
      <p role="status" className="mb-2 text-sm">
        {message}
      </p>
      <progress
        className="w-full"
        aria-label={message}
        value={progress.page}
        max={progress.pages}
      />
    </Dialog>
  )
}

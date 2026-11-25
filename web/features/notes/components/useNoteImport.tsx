'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { Dialog } from '@/shared/ui/Dialog'
import { activeWorkspaceId, scopedUrl } from '@/lib/workspace-scope'
import { notifyCoWriterChanged } from '@/lib/co-writer-events'
import type { NoteSummary } from '@/lib/notes-api'
import { prepareNoteDestination } from './useNoteNavigation'
import { importNoteDocument, type ImportProgress } from '../model/import-document'

export function useNoteImport(
  pages: NoteSummary[],
  onError: (message: string) => void,
  treeOpen = false
) {
  const router = useRouter()
  const { t } = useTranslation()
  const [fileName, setFileName] = useState('')
  const [visible, setVisible] = useState(false)
  const [progress, report] = useState<ImportProgress>({ label: 'Reading file' })
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  useEffect(() => {
    if (!fileName) return
    const timer = setTimeout(() => setVisible(true), 500)
    return () => clearTimeout(timer)
  }, [fileName])

  const openFile = async (file: File, beforeImport?: () => Promise<void>) => {
    const workspace = activeWorkspaceId()
    onError('')
    setFileName(file.name)
    report({ label: beforeImport ? 'Saving…' : 'Reading file' })
    try {
      await beforeImport?.()
      report({ label: 'Reading file' })
      const { default: Editor } = await import('./NoteEditor')
      // BlockNote parses Markdown synchronously. Paint progress before a large parse
      // gets the main thread, otherwise the delayed dialog cannot appear until it ends.
      if (/\.(md|markdown)$/i.test(file.name) && file.size >= 256 * 1024) {
        setVisible(true)
        report({ label: 'Processing…' })
        await new Promise<void>(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)))
      }
      if (!mounted.current) return
      if (workspace !== activeWorkspaceId()) throw new Error(t('Cancelled'))
      const doc = await importNoteDocument(file, t, report)
      if (!mounted.current) return
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
      router.push(scopedUrl(`/co-writer/${doc.id}`, workspace))
    } catch (err) {
      setFileName('')
      setVisible(false)
      onError(err instanceof Error ? err.message : String(err))
    }
  }

  const message = progress.pages
    ? t('Page {{page}} of {{pages}}', { page: progress.page, pages: progress.pages })
    : t(progress.label)
  const dialog = visible && (
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
  return { openFile, importing: !!fileName, dialog }
}

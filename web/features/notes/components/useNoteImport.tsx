'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import dynamic from 'next/dynamic'
import { activeWorkspaceId } from '@/lib/workspace-scope'
import type { NoteSummary } from '@/lib/notes-api'
import type { ImportProgress } from '../model/import-document'

export const noteDocumentTypes = '.docx,.md,.markdown,.pdf'
const Progress = dynamic(
  () => import('./NoteImportProgress').then(module => module.NoteImportProgress),
  {
    ssr: false,
  }
)

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
      const { openImportedFile } = await import('./NoteImportProgress')
      await openImportedFile(file, {
        beforeImport,
        report,
        showProgress: () => setVisible(true),
        workspace,
        isMounted: () => mounted.current,
        pages,
        treeOpen,
        navigate: url => router.push(url),
        t,
      })
    } catch (err) {
      setFileName('')
      setVisible(false)
      onError(err instanceof Error ? err.message : String(err))
    }
  }

  const dialog = visible && <Progress fileName={fileName} progress={progress} />
  return { openFile, importing: !!fileName, dialog }
}

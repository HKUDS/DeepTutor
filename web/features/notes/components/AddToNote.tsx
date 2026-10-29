'use client'
import Link from 'next/link'
import type { FavoriteSnapshot } from '@/lib/favorite-content'
import { useState } from 'react'
import { FilePlus2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  listNotes,
  createNote,
  getNote,
  saveNote,
  noteRequest,
  type NoteSummary,
} from '@/lib/notes-api'
import { notifyCoWriterChanged } from '@/lib/co-writer-events'
export default function AddToNote({
  title,
  markdown,
  sourceUrl = '',
  sourceId = '',
  onSaved,
  favorite,
  className = 'px-5 py-3 text-sm',
}: {
  title: string
  markdown: string
  sourceUrl?: string
  sourceId?: string
  onSaved?: () => void
  favorite?: FavoriteSnapshot
  /** The wrapper's box; a toolbar passes its own. */
  className?: string
}) {
  const { t } = useTranslation()
  const [pages, setPages] = useState<NoteSummary[] | null>(null)
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const save = async () => {
    setBusy(true)
    setError('')
    try {
      let id = target
      if (!id) {
        const doc = await createNote(title)
        id = doc.id
        setTarget(id)
        setPages(current => [{ ...doc, preview: doc.content.slice(0, 160) }, ...(current || [])])
      }
      const page = await getNote(id)
      if (page.blocks === null && page.content.trim()) {
        const { parseLegacyNoteContent } = await import('./NoteEditor')
        await saveNote(id, {
          blocks: parseLegacyNoteContent(page.content),
          expected_revision: page.revision,
        })
      }
      await noteRequest(`/${id}/clips`, {
        title,
        markdown,
        source_url: sourceUrl,
        source_id: sourceId,
        favorite_type: favorite?.type || '',
        summary: favorite?.summary || '',
        favorite_metadata: favorite?.metadata || {},
      })
      setSaved(true)
      notifyCoWriterChanged()
      onSaved?.()
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className={className}>
      {pages === null ? (
        <button
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 hover:bg-[var(--secondary)]"
          onClick={() => {
            void listNotes()
              .then(r => setPages(r.documents))
              .catch(e => setError(String(e)))
          }}
        >
          <FilePlus2 size={14} strokeWidth={1.7} />
          {t('Add to a note')}
        </button>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={t('Target page')}
            className="max-w-64 rounded bg-[var(--secondary)] p-2"
            value={target}
            onChange={e => {
              setTarget(e.target.value)
              setSaved(false)
            }}
          >
            <option value="">{t('New page')}</option>
            {pages.map(p => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
          <button
            className="rounded px-2 py-1.5 hover:bg-[var(--secondary)]"
            disabled={busy || saved || !markdown.trim()}
            onClick={() => void save()}
          >
            {t(saved ? 'Added to note' : busy ? 'Saving…' : 'Add to a note')}
          </button>
          {saved && target && (
            <Link
              href={`/co-writer/${target}`}
              className="rounded px-2 py-1.5 text-[var(--primary)] hover:underline"
            >
              {t('Open note')}
            </Link>
          )}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}

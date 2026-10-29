'use client'
import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useTopicSourceLibrary,
  sourceRequest,
  type SourceCandidate,
} from '@/hooks/useTopicSourceLibrary'
import { scopedUrl } from '@/lib/workspace-scope'
import PickerShell from '@/components/common/PickerShell'
import type { NotePage } from '@/lib/notes-api'

export default function NoteSourcePicker({
  onClose,
  onInsert,
  onKnowledge,
}: {
  onClose: () => void
  onInsert: (title: string, markdown: string, url: string, id: string) => void
  onKnowledge: (name: string, workspace: string) => void
}) {
  const { t, i18n } = useTranslation()
  const tr = useCallback(
    (zh: string, en: string) => (i18n.language.startsWith('zh') ? zh : en),
    [i18n.language]
  )
  const { library, loading } = useTopicSourceLibrary(tr)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const items = [...library.drafts, ...library.chats, ...library.knowledgeBases].filter(
    row => row.available && row.label.toLowerCase().includes(query.toLowerCase())
  )
  const select = async (row: SourceCandidate) => {
    setBusy(true)
    try {
      if (row.kind === 'knowledge_base') {
        onKnowledge(row.sourceId, row.content_workspace_id ?? '')
        onClose()
        return
      }
      let text = row.excerpt || row.detail
      if (row.kind === 'cowriter') {
        const page = await sourceRequest<NotePage>(
          `/api/documents/${row.sourceId}`,
          row.content_workspace_id
        )
        text = page.content
      } else if (row.kind === 'chat') {
        const session = await sourceRequest<{ messages: { role: string; content: unknown }[] }>(
          `/api/sessions/${row.sourceId}`,
          row.content_workspace_id
        )
        text = (session.messages || [])
          .filter(m => ['user', 'assistant'].includes(m.role))
          .map(
            m => `${m.role === 'user' ? t('Question') : t('Answer')}\n\n${String(m.content || '')}`
          )
          .join('\n\n')
          .slice(0, 180000)
      }
      const path = row.kind === 'cowriter' ? `/co-writer/${row.sourceId}` : `/chat/${row.sourceId}`
      onInsert(row.label, text, scopedUrl(path, row.content_workspace_id), row.sourceId)
      onClose()
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <PickerShell open onClose={onClose} ariaLabel={t('Reference a source')}>
      <div className="w-[min(540px,90vw)] rounded-xl bg-[var(--card)] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium">{t('Reference a source')}</h2>
          <button className="dt-note-button" onClick={onClose}>
            {t('Close')}
          </button>
        </div>
        <input
          autoFocus
          aria-label={t('Search sources')}
          placeholder={t('Search sources')}
          className="mb-3 w-full rounded bg-[var(--secondary)] p-2 text-sm"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <div className="max-h-96 overflow-y-auto">
          {loading ? (
            <p>…</p>
          ) : (
            items.map(row => (
              <button
                key={row.key}
                disabled={busy}
                className="block w-full rounded px-2 py-2 text-left text-sm hover:bg-[var(--secondary)]"
                onClick={() => void select(row)}
              >
                <span>{row.label}</span>
                <span className="block text-xs text-[var(--muted-foreground)]">
                  {t(
                    row.kind === 'cowriter'
                      ? 'Learning notebook'
                      : row.kind === 'chat'
                        ? 'Conversation'
                        : 'Knowledge base'
                  )}{' '}
                  · {row.content_workspace_name}
                </span>
              </button>
            ))
          )}
        </div>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </div>
    </PickerShell>
  )
}

'use client'

import { useState } from 'react'
import { Archive, ArchiveRestore, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import './note-page-actions.css'

export type PageAction = 'archive' | 'restore' | 'delete'

export default function NotePageActions({
  page,
  hasChildren,
  current = false,
  compact = false,
  onAction,
}: {
  page: { title: string; archived?: boolean }
  hasChildren: boolean
  current?: boolean
  compact?: boolean
  onAction: (action: PageAction) => void
}) {
  const { t } = useTranslation()
  const [confirming, setConfirming] = useState(false)
  return (
    <>
      <button
        role="menuitem"
        className="dt-menu-item"
        onClick={() => onAction(page.archived ? 'restore' : 'archive')}
      >
        {page.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
        {t(page.archived ? 'Restore' : current ? 'Archive current page' : 'Archive')}
      </button>
      {confirming && (!compact || hasChildren) && (
        <p className="dt-notes-confirm" role="status">
          {!compact && <strong title={page.title}>{page.title || t('Untitled')}</strong>}
          {t(
            hasChildren
              ? 'Delete this page? Its subpages move up one level.'
              : 'Delete this page? This cannot be undone.'
          )}
        </p>
      )}
      <button
        role="menuitem"
        className="dt-menu-item is-danger"
        onClick={() => (confirming ? onAction('delete') : setConfirming(true))}
      >
        <Trash2 size={14} />
        {t(
          confirming
            ? compact
              ? 'Confirm delete'
              : 'Delete page'
            : current
              ? 'Delete current page'
              : 'Delete'
        )}
      </button>
    </>
  )
}

'use client'

import { useEffect, useState, type ComponentProps } from 'react'
import { createPortal } from 'react-dom'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import { placeMenu } from '@/lib/floating-menu'
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

export function TreeMenu({
  anchor,
  trigger,
  onClose,
  ...actions
}: ComponentProps<typeof NotePageActions> & {
  anchor: DOMRect
  trigger: HTMLButtonElement
  onClose: () => void
}) {
  const { t } = useTranslation()
  const panel = useMenuPopover<HTMLDivElement>(true, onClose, trigger)
  const width = 200
  const position = placeMenu(anchor, width)
  useEffect(() => {
    window.addEventListener('resize', onClose)
    return () => window.removeEventListener('resize', onClose)
  }, [onClose])
  return createPortal(
    <div
      ref={panel}
      className="dt-popover dt-note-tree-menu"
      role="menu"
      aria-label={actions.page.title || t('Untitled')}
      style={{
        width,
        left: position.left,
        top: position.top,
        maxHeight: position.maxHeight,
        translate: position.openUpward ? '0 -100%' : undefined,
      }}
    >
      <NotePageActions {...actions} />
    </div>,
    document.body
  )
}

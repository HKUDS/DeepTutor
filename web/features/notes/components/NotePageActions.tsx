'use client'

import { useEffect, useState, type ComponentProps } from 'react'
import { createPortal } from 'react-dom'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import { placeMenu } from '@/lib/floating-menu'
import { Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import './note-page-actions.css'

export default function NotePageActions({
  page,
  hasChildren,
  current = false,
  compact = false,
  onDelete,
}: {
  page: { title: string }
  hasChildren: boolean
  current?: boolean
  compact?: boolean
  onDelete: () => void
}) {
  const { t } = useTranslation()
  const [confirming, setConfirming] = useState(false)
  return (
    <>
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
        onClick={() => (confirming ? onDelete() : setConfirming(true))}
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

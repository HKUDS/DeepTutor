'use client'

import { useEffect, useState, type ComponentProps } from 'react'
import { createPortal } from 'react-dom'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import { Pin, PinOff, Trash2 } from 'lucide-react'
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
  trigger,
  onClose,
  onPin,
  pinned,
  ...actions
}: ComponentProps<typeof NotePageActions> & {
  onPin?: () => void
  pinned: boolean
  trigger: HTMLButtonElement
  onClose: () => void
}) {
  const { t } = useTranslation()
  const panel = useMenuPopover<HTMLDivElement>(true, onClose, trigger)
  const anchor = trigger.closest('.dt-note-tree-row')!.getBoundingClientRect()
  const width = 200
  const below = window.innerHeight - anchor.bottom
  const above = anchor.top
  const openUpward = below < 140 && above > below
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
        left: Math.max(0, Math.min(anchor.right - width, window.innerWidth - width)),
        top: openUpward ? anchor.top : anchor.bottom,
        maxHeight: openUpward ? above : below,
        translate: openUpward ? '0 -100%' : undefined,
      }}
    >
      {onPin && (
        <button role="menuitem" className="dt-menu-item" onClick={onPin}>
          {pinned ? <PinOff size={14} /> : <Pin size={14} />}
          {t(pinned ? 'Unpin' : 'Pin to top')}
        </button>
      )}
      <NotePageActions {...actions} />
    </div>,
    document.body
  )
}

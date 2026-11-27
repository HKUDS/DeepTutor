'use client'

import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ImageIcon, SmilePlus } from 'lucide-react'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import type { NotePage } from '@/lib/notes-api'

/** A short shelf of study-flavoured marks; the field below takes any emoji. */
const PAGE_ICONS = [
  '📘', '📗', '📙', '📕', '📓', '📒', '📝', '✏️',
  '📌', '🔖', '🧠', '💡', '🔬', '🧪', '🧬', '🧮',
  '📐', '🗺️', '🌍', '🌱', '🌊', '🔥', '⭐', '✨',
  '🎯', '🎨', '🎵', '🏛️', '⚛️', '🧭', '📊', '📈',
  '🗂️', '✅', '❓', '💬', '🪐', '🦉', '🍎', '☕',
]

/** Quiet paper tones first, then soft gradients. Stored as CSS backgrounds. */
const PAGE_COVERS = [
  '#e6e4dc',
  '#dce5dd',
  '#dce3eb',
  '#eee0d6',
  '#e6deeb',
  '#efe6c8',
  'linear-gradient(120deg, #e8e2d4 0%, #d6e2e9 100%)',
  'linear-gradient(120deg, #f1dfd2 0%, #e5dcef 100%)',
  'linear-gradient(120deg, #d9e8dc 0%, #e8efcf 100%)',
  'linear-gradient(120deg, #dfe6f3 0%, #f1e4ec 100%)',
]

function Picker({
  open,
  setOpen,
  className,
  children,
  trigger,
}: {
  open: boolean
  setOpen: (open: boolean) => void
  className?: string
  children: React.ReactNode
  trigger: React.ReactNode
}) {
  const root = useMenuPopover<HTMLDivElement>(open, value =>
    setOpen(typeof value === 'function' ? value(open) : value)
  )
  return (
    <div ref={root} className={`relative ${className ?? ''}`}>
      {trigger}
      {open && <div className="dt-popover dt-note-picker">{children}</div>}
    </div>
  )
}

export default function NotePageHead({
  page,
  disabled,
  onTitle,
  onMetadata,
}: {
  page: NotePage
  disabled: boolean
  onTitle: (title: string) => void
  onMetadata: (patch: Partial<NotePage>) => void
}) {
  const { t } = useTranslation()
  const [iconOpen, setIconOpen] = useState(false)
  const [coverOpen, setCoverOpen] = useState(false)
  const [customIcon, setCustomIcon] = useState('')
  const title = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = title.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${el.scrollHeight}px`
  }, [page.title])
  const openIcons = (open: boolean) => {
    setIconOpen(open)
    if (!open) setCustomIcon('')
  }
  const pickIcon = (icon: string) => {
    openIcons(false)
    onMetadata({ icon })
  }
  const coverPicker = (trigger: React.ReactNode) => (
    <Picker open={coverOpen} setOpen={setCoverOpen} trigger={trigger}>
      <div className="dt-menu-label">{t('Cover')}</div>
      <div className="dt-note-cover-grid">
        {PAGE_COVERS.map(cover => (
          <button
            key={cover}
            role="menuitemradio"
            aria-label={t('Set cover color', { color: cover })}
            aria-checked={page.cover === cover}
            style={{ background: cover }}
            onClick={() => {
              setCoverOpen(false)
              onMetadata({ cover })
            }}
          />
        ))}
      </div>
      {page.cover && (
        <>
          <div className="dt-menu-divider" />
          <button
            role="menuitem"
            className="dt-menu-item is-quiet"
            onClick={() => {
              setCoverOpen(false)
              onMetadata({ cover: '' })
            }}
          >
            {t('Remove cover')}
          </button>
        </>
      )}
    </Picker>
  )
  const iconPicker = (trigger: React.ReactNode, className?: string) => (
    <Picker open={iconOpen} setOpen={openIcons} trigger={trigger} className={className}>
      <div className="dt-menu-label">{t('Page icon')}</div>
      <div className="dt-note-icon-grid">
        {PAGE_ICONS.map(icon => (
          <button
            key={icon}
            role="menuitemradio"
            aria-label={icon}
            aria-checked={page.icon === icon}
            onClick={() => pickIcon(icon)}
          >
            {icon}
          </button>
        ))}
      </div>
      <form
        className="dt-note-icon-custom"
        onSubmit={e => {
          e.preventDefault()
          if (customIcon.trim()) pickIcon(customIcon.trim())
        }}
      >
        <input
          aria-label={t('Any emoji')}
          placeholder={t('Paste any emoji…')}
          maxLength={10}
          value={customIcon}
          onChange={e => setCustomIcon(e.target.value)}
        />
      </form>
      {page.icon && (
        <>
          <div className="dt-menu-divider" />
          <button role="menuitem" className="dt-menu-item is-quiet" onClick={() => pickIcon('')}>
            {t('Remove icon')}
          </button>
        </>
      )}
    </Picker>
  )
  return (
    <div className={`dt-note-head ${page.cover ? 'has-cover' : ''} ${page.icon ? 'has-icon' : ''}`}>
      {page.cover && (
        <div className="dt-note-cover" style={{ background: page.cover }}>
          <div className="dt-note-cover-actions">
            {coverPicker(
              <button
                className="dt-note-ghost"
                disabled={disabled}
                aria-haspopup="menu"
                aria-expanded={coverOpen}
                onClick={() => setCoverOpen(!coverOpen)}
              >
                {t('Change cover')}
              </button>
            )}
          </div>
        </div>
      )}
      <div className="dt-note-head-body">
        {page.icon &&
          iconPicker(
            <button
              className="dt-note-page-icon"
              disabled={disabled}
              aria-label={t('Change icon')}
              aria-haspopup="menu"
              aria-expanded={iconOpen}
              onClick={() => openIcons(!iconOpen)}
            >
              {page.icon}
            </button>,
            'dt-note-page-icon-wrap'
          )}
        <div className="dt-note-head-tools">
          {!page.icon &&
            iconPicker(
              <button
                className="dt-note-ghost"
                disabled={disabled}
                aria-haspopup="menu"
                aria-expanded={iconOpen}
                onClick={() => openIcons(!iconOpen)}
              >
                <SmilePlus size={15} strokeWidth={1.7} />
                {t('Add icon')}
              </button>
            )}
          {!page.cover &&
            coverPicker(
              <button
                className="dt-note-ghost"
                disabled={disabled}
                aria-haspopup="menu"
                aria-expanded={coverOpen}
                onClick={() => setCoverOpen(!coverOpen)}
              >
                <ImageIcon size={15} strokeWidth={1.7} />
                {t('Add cover')}
              </button>
            )}
        </div>
        <textarea
          ref={title}
          rows={1}
          disabled={disabled}
          aria-label={t('Page title')}
          placeholder={t('Untitled')}
          className="dt-note-page-title"
          value={page.title}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault()
              const editor = e.currentTarget
                .closest('.dt-note-document')
                ?.querySelector<HTMLElement>('.bn-editor')
              if (editor) editor.focus()
              else e.currentTarget.blur()
            }
          }}
          onChange={e => onTitle(e.target.value)}
        />
      </div>
    </div>
  )
}

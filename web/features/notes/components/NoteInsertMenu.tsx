'use client'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, Search, CornerDownLeft } from 'lucide-react'
import {
  useExtension,
  type DefaultReactSuggestionItem,
  type SuggestionMenuProps,
} from '@blocknote/react'
import NoteBlockPreview from './NoteBlockPreview'
import type { BlockPreviewKind } from '../model/block-previews'
import { SuggestionMenu } from '@blocknote/core/extensions'
export type NoteMenuItem = DefaultReactSuggestionItem & {
  key?: string
  shortcut?: string
  preview: BlockPreviewKind
  previewTitle?: string
}
export default function NoteInsertMenu({
  items,
  selectedIndex,
  loadingState,
  onItemClick,
}: SuggestionMenuProps<NoteMenuItem>) {
  const { t } = useTranslation()
  const extension = useExtension(SuggestionMenu)
  const root = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<{ index: number; signature: string } | null>(null)
  const [previewSide, setPreviewSide] = useState('inline')
  const signature = items.map(item => item.title).join('\n')
  const hoverIndex = hover?.signature === signature ? hover.index : null
  const index = Math.min(hoverIndex ?? selectedIndex ?? 0, items.length - 1)
  const selected = items[index]
  useEffect(() => {
    const reveal = () =>
      list.current
        ?.querySelector(`[data-index="${selectedIndex ?? 0}"]`)
        ?.scrollIntoView({ block: 'nearest' })
    reveal()
    const observer = new ResizeObserver(reveal)
    if (list.current) observer.observe(list.current)
    return () => observer.disconnect()
  }, [selectedIndex])
  useEffect(() => {
    const keyboard = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && hoverIndex !== null && items[hoverIndex]) {
        e.preventDefault()
        e.stopPropagation()
        onItemClick?.(items[hoverIndex])
      }
      if (['ArrowUp', 'ArrowDown', 'Enter'].includes(e.key)) setHover(null)
    }
    document.addEventListener('keydown', keyboard, true)
    return () => document.removeEventListener('keydown', keyboard, true)
  }, [hoverIndex, items, onItemClick])
  useEffect(() => {
    const measure = () => {
      const rect = root.current?.getBoundingClientRect()
      if (rect)
        setPreviewSide(
          window.innerWidth - rect.right > 246 ? 'right' : rect.left > 246 ? 'left' : 'inline'
        )
    }
    measure()
    const observer = new ResizeObserver(measure)
    if (root.current) observer.observe(root.current)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [])
  return (
    <div
      ref={root}
      className={`dt-note-insert-menu preview-${previewSide}`}
      onMouseLeave={() => setHover(null)}
    >
      <div className="dt-note-menu-hint">
        <Search size={13} />
        {t('Type to filter blocks')}
      </div>
      <div
        ref={list}
        id="bn-suggestion-menu"
        className="dt-note-menu-items"
        role="listbox"
        aria-label={t('Insert block')}
      >
        {!items.length && (
          <p className="dt-note-hint">
            {t(loadingState === 'loaded' ? 'No matching blocks' : 'Loading…')}
          </p>
        )}
        {items.map((item, i) => (
          <div key={`${item.title}-${i}`}>
            {(i === 0 || item.group !== items[i - 1].group) && (
              <div className="dt-note-menu-group">{item.group || t('Pages')}</div>
            )}
            <button
              role="option"
              id={`bn-suggestion-menu-item-${i}`}
              aria-selected={i === index}
              aria-describedby={item.subtext ? `dt-note-menu-description-${i}` : undefined}
              data-index={i}
              className={i === index ? 'selected' : ''}
              onMouseEnter={() => setHover({ index: i, signature })}
              onMouseDown={e => e.preventDefault()}
              onClick={() => onItemClick?.(item)}
            >
              <span className="dt-note-menu-icon">{item.icon || <FileText size={19} />}</span>
              <span>{item.title}</span>
              {item.shortcut && <kbd>{item.shortcut}</kbd>}
            </button>
            {item.subtext && (
              <span className="sr-only" id={`dt-note-menu-description-${i}`}>
                {item.subtext}
              </span>
            )}
          </div>
        ))}
      </div>
      <footer>
        <button onMouseDown={e => e.preventDefault()} onClick={() => extension.closeMenu()}>
          {t('Close menu')}
          <kbd>{t('esc')}</kbd>
        </button>
        <span>
          <CornerDownLeft size={12} />
          {t('Select')}
        </span>
      </footer>
      {selected && (
        <aside className={`dt-note-menu-preview ${previewSide}`} aria-hidden="true">
          <div className="dt-note-preview-example" data-preview-kind={selected.preview}>
            <NoteBlockPreview kind={selected.preview} title={selected.previewTitle} />
          </div>
          <strong>{selected.title}</strong>
          <p>{selected.subtext || t('Insert this block at the cursor.')}</p>
        </aside>
      )}
    </div>
  )
}

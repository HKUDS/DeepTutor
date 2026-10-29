'use client'
/**
 * A favorite placed on a note page: the saved original, read-only, with its
 * way back to where it was saved.
 *
 * Collapsed it is one quiet card — what kind of thing it is, where it came
 * from, its title and gist. Opening it shows the original in place, capped
 * to a reading height with "Show all" for long ones, so a forty-turn
 * conversation does not push the rest of the page off the screen.
 */
import '@/components/notebook/favorites.css'
import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowUpRight, ChevronDown } from 'lucide-react'
import FavoriteContent from '@/components/notebook/NotebookFavoriteContent'
import { FavoriteKindIcon, favoriteLabel } from '@/components/notebook/favorite-kinds'
import { favoriteKind } from '@/lib/favorite-content'
import { formatRelativeTime } from '@/lib/relative-time'
import Tooltip from '@/shared/ui/Tooltip'

const BODY_CAP = 520

export default function NoteFavoriteBlock({
  title,
  markdown,
  sourceUrl,
  type,
  summary,
  metadata,
  expanded,
  onExpanded,
  onActivate,
}: {
  title: string
  markdown: string
  sourceUrl: string
  type: string
  summary: string
  metadata: string
  expanded: boolean
  onExpanded: (open: boolean) => void
  onActivate?: () => void
}) {
  const { t, i18n } = useTranslation()
  let meta: Record<string, unknown> = {}
  try {
    const value = JSON.parse(metadata)
    if (value && typeof value === 'object' && !Array.isArray(value)) meta = value
  } catch {
    /* Legacy clips have no structured metadata. */
  }
  const kind = favoriteKind(type, meta)
  const collection = typeof meta.favorite_collection === 'string' ? meta.favorite_collection : ''
  const savedAt = typeof meta.favorite_saved_at === 'number' ? meta.favorite_saved_at : 0
  const body = useRef<HTMLDivElement>(null)
  const [showAll, setShowAll] = useState(false)
  const [overflows, setOverflows] = useState(false)
  const toggle = () => {
    setShowAll(false)
    onExpanded(!expanded)
  }
  useLayoutEffect(() => {
    if (!expanded) return
    const el = body.current
    if (!el) return
    const measure = () => setOverflows(el.scrollHeight > BODY_CAP + 24)
    measure()
    // Markdown, KaTeX and media settle after the first paint.
    const observer = new ResizeObserver(measure)
    observer.observe(el.firstElementChild || el)
    return () => observer.disconnect()
  }, [expanded])
  return (
    <div
      className={`dt-note-favorite${expanded ? ' is-open' : ''}`}
      contentEditable={false}
      onFocusCapture={onActivate}
      onMouseDownCapture={event => {
        onActivate?.()
        event.stopPropagation()
      }}
      onClick={event => event.stopPropagation()}
    >
      <div className="dt-note-favorite-head">
        <button
          type="button"
          className="dt-note-favorite-toggle"
          aria-expanded={expanded}
          aria-label={`${title || t('Favorite content')} · ${t('Saved original')}`}
          onClick={toggle}
        >
          <FavoriteKindIcon kind={kind} size={17} />
          <span className="min-w-0 flex-1 text-left">
            <span className="dt-note-favorite-kind">
              {t(favoriteLabel(kind))}
              {collection ? (
                <> · {t('From “{{name}}”', { name: collection })}</>
              ) : (
                <> · {t('Saved original')}</>
              )}
              {savedAt ? <> · {formatRelativeTime(savedAt, i18n.language)}</> : null}
            </span>
            <strong className="dt-note-favorite-title">{title || t('Favorite content')}</strong>
            {summary && !expanded && <span className="dt-note-favorite-summary">{summary}</span>}
          </span>
        </button>
        <div className="dt-note-favorite-tools">
          {sourceUrl && (
            <Tooltip label={t('Return to source')}>
              <a data-note-source href={sourceUrl} aria-label={t('Return to source')}>
                <ArrowUpRight size={15} strokeWidth={1.8} />
              </a>
            </Tooltip>
          )}
          <Tooltip label={t(expanded ? 'Hide original content' : 'Show original content')}>
            <button
              type="button"
              aria-label={t(expanded ? 'Hide original content' : 'Show original content')}
              onClick={toggle}
            >
              <ChevronDown size={16} strokeWidth={1.8} className={expanded ? 'rotate-180' : ''} />
            </button>
          </Tooltip>
        </div>
      </div>
      {expanded && (
        <div
          ref={body}
          className={`dt-note-favorite-body${overflows && !showAll ? ' is-capped' : ''}`}
          style={overflows && !showAll ? { maxHeight: BODY_CAP } : undefined}
        >
          <FavoriteContent type={type} markdown={markdown} metadata={meta} />
        </div>
      )}
      {expanded && overflows && (
        <button
          type="button"
          className="dt-note-favorite-more"
          onClick={() => setShowAll(!showAll)}
        >
          {t(showAll ? 'Show less' : 'Show all')}
          <ChevronDown size={14} className={showAll ? 'rotate-180' : ''} />
        </button>
      )}
    </div>
  )
}

'use client'
/**
 * Insert favorites into a note.
 *
 * A two-pane library rather than a dropdown: collections on the left (with
 * "All favorites" first, so the common case — "that thing I saved" — needs no
 * idea of where it was filed), the saved items on the right, searchable across
 * everything. Picks are numbered in the order they were made, and that is the
 * order they land on the page: the learner composes the section while
 * choosing. Any item can be previewed in place before it is chosen.
 */
import '@/components/notebook/favorites.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ChevronDown, Library, Search, Sparkles, X } from 'lucide-react'
import {
  getNotebook,
  listNotebooks,
  type NotebookRecordItem,
  type NotebookSummary,
} from '@/lib/notebook-api'
import { favoriteKind, favoriteSnapshot } from '@/lib/favorite-content'
import { favoriteRecordRoute } from '@/lib/resource-routes'
import { formatRelativeTime } from '@/lib/relative-time'
import PickerShell from '@/components/common/PickerShell'
import FavoriteContent from '@/components/notebook/NotebookFavoriteContent'
import { FavoriteKindIcon, favoriteLabel } from '@/components/notebook/favorite-kinds'
import type { NoteClipInput } from '../model/clip-editing'

type Item = NotebookRecordItem & { collection: NotebookSummary }
const ALL = ''

const keyOf = (item: Item) => `${item.collection.id}/${item.id}`

export default function NoteFavoritesPicker({
  onClose,
  onInsert,
  onSynthesize,
}: {
  onClose: () => void
  onSynthesize: (sources: string) => void
  onInsert: (clips: NoteClipInput[]) => void
}) {
  const { t, i18n } = useTranslation()
  const [collections, setCollections] = useState<NotebookSummary[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [collection, setCollection] = useState(ALL)
  const [kind, setKind] = useState('')
  const [query, setQuery] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [preview, setPreview] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const search = useRef<HTMLInputElement>(null)

  // Everything is loaded once: collections are small, and searching across
  // all of them is what makes "All favorites" useful.
  useEffect(() => {
    let cancelled = false
    void listNotebooks()
      .then(async list => {
        const readable = list.filter(item => !item.unreadable)
        if (cancelled) return
        setCollections(readable)
        const details = await Promise.all(
          readable.map(c =>
            getNotebook(c.id)
              .then(detail => detail.records.map(record => ({ ...record, collection: c })))
              .catch(() => [] as Item[])
          )
        )
        if (!cancelled) setItems(details.flat())
      })
      .catch(() => {
        if (!cancelled) setError(t('Could not load favorites.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  const counts = useMemo(() => {
    const map = new Map<string, number>()
    for (const item of items) map.set(item.collection.id, (map.get(item.collection.id) || 0) + 1)
    return map
  }, [items])
  const scoped = useMemo(() => {
    const inScope = collection ? items.filter(item => item.collection.id === collection) : items
    // "All" reads newest first; a collection keeps the order it was filed in.
    return collection
      ? inScope
      : [...inScope].sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
  }, [collection, items])
  const kinds = useMemo(
    () => [...new Set(scoped.map(item => favoriteKind(item.type, item.metadata)))],
    [scoped]
  )
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return scoped.filter(
      item =>
        (!kind || favoriteKind(item.type, item.metadata) === kind) &&
        (!needle ||
          `${item.title} ${item.summary || ''} ${item.output}`.toLowerCase().includes(needle))
    )
  }, [kind, query, scoped])
  const byKey = useMemo(() => new Map(items.map(item => [keyOf(item), item])), [items])
  const chosen = picked.flatMap(key => byKey.get(key) ?? [])

  const toggle = (item: Item) =>
    setPicked(previous =>
      previous.includes(keyOf(item))
        ? previous.filter(key => key !== keyOf(item))
        : [...previous, keyOf(item)]
    )
  const insert = () => {
    if (!chosen.length) return
    onInsert(
      chosen.map(item => ({
        title: item.title,
        markdown: item.output,
        sourceUrl: favoriteRecordRoute(item.collection.id, item.id),
        sourceId: item.id,
        favorite: favoriteSnapshot(item, item.collection),
      }))
    )
    onClose()
  }
  const synthesize = () => {
    if (!chosen.length) return
    onSynthesize(
      chosen
        .map(
          item =>
            `## ${item.title}\n\n${item.output}\n\n[${item.title}](${favoriteRecordRoute(item.collection.id, item.id)})`
        )
        .join('\n\n')
    )
    onClose()
  }
  const active = collections.find(c => c.id === collection)
  const empty = loading
    ? ''
    : !items.length
      ? t('Nothing saved yet. Save a conversation or result to Favorites to use it here.')
      : !scoped.length
        ? t('No favorites in this collection yet.')
        : t('No records match your search')

  return (
    <PickerShell open onClose={onClose} labelledBy="dt-fav-picker-title">
      <div
        className="dt-fav-picker"
        onKeyDown={event => {
          if (
            event.key === 'Enter' &&
            (event.metaKey || event.ctrlKey) &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault()
            insert()
          }
        }}
      >
        <header className="dt-fav-picker-head">
          <h2 id="dt-fav-picker-title">{t('Insert favorite')}</h2>
          <label className="dt-fav-search">
            <Search size={15} strokeWidth={1.8} aria-hidden />
            <input
              ref={search}
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder={
                active
                  ? t('Search in “{{name}}”', { name: active.name })
                  : t('Search all favorites')
              }
              aria-label={t('Search favorites')}
            />
            {query && (
              <button
                type="button"
                aria-label={t('Clear search')}
                onClick={() => {
                  setQuery('')
                  search.current?.focus()
                }}
              >
                <X size={13} />
              </button>
            )}
          </label>
          <button
            type="button"
            className="dt-fav-icon-button"
            aria-label={t('Close')}
            onClick={onClose}
          >
            <X size={16} strokeWidth={1.7} />
          </button>
        </header>
        <div className="dt-fav-picker-body">
          <nav className="dt-fav-collections" aria-label={t('Favorites')}>
            <button
              type="button"
              aria-pressed={collection === ALL}
              onClick={() => {
                setCollection(ALL)
                setKind('')
              }}
            >
              <Library size={15} strokeWidth={1.7} className="dt-fav-collection-icon" />
              <span className="truncate">{t('All favorites')}</span>
              <span className="dt-fav-count">{items.length || ''}</span>
            </button>
            {!!collections.length && <p className="dt-fav-rail-label">{t('Folders')}</p>}
            {collections.map(c => (
              <button
                key={c.id}
                type="button"
                aria-pressed={collection === c.id}
                onClick={() => {
                  setCollection(c.id)
                  setKind('')
                }}
              >
                <span
                  className="dt-fav-dot"
                  style={{ background: c.color || 'var(--folder-default)' }}
                />
                <span className="truncate">{c.name}</span>
                <span className="dt-fav-count">{counts.get(c.id) || 0}</span>
              </button>
            ))}
          </nav>
          <section className="dt-fav-records" aria-busy={loading}>
            {kinds.length > 1 && (
              <div className="dt-fav-chips" role="group" aria-label={t('Type')}>
                <button type="button" aria-pressed={!kind} onClick={() => setKind('')}>
                  {t('All')}
                </button>
                {kinds.map(value => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={kind === value}
                    onClick={() => setKind(kind === value ? '' : value)}
                  >
                    {t(favoriteLabel(value))}
                  </button>
                ))}
              </div>
            )}
            {loading && (
              <div className="dt-fav-skeleton" role="status" aria-label={t('Loading...')}>
                {[0, 1, 2, 3].map(i => (
                  <span key={i} />
                ))}
              </div>
            )}
            {!loading && !visible.length && !error && <p className="dt-fav-empty">{empty}</p>}
            {error && (
              <p role="alert" className="dt-fav-empty is-error">
                {error}
              </p>
            )}
            <ul className="dt-fav-list">
              {visible.map(item => {
                const key = keyOf(item)
                const order = picked.indexOf(key)
                const itemKind = favoriteKind(item.type, item.metadata)
                const open = preview === key
                return (
                  <li key={key} className={order >= 0 ? 'is-picked' : undefined}>
                    <div className="dt-fav-row">
                      <label className="dt-fav-row-main">
                        <input
                          type="checkbox"
                          className="sr-only"
                          checked={order >= 0}
                          onChange={() => toggle(item)}
                          aria-label={[item.title, item.summary].filter(Boolean).join(' — ')}
                        />
                        <span className="dt-fav-check" aria-hidden>
                          {order >= 0 ? (
                            picked.length > 1 ? (
                              order + 1
                            ) : (
                              <Check size={12} strokeWidth={3} />
                            )
                          ) : null}
                        </span>
                        <FavoriteKindIcon kind={itemKind} />
                        <span className="min-w-0 flex-1">
                          <span className="dt-fav-title">
                            {item.title || t('Favorite content')}
                          </span>
                          {item.summary && <span className="dt-fav-summary">{item.summary}</span>}
                          <span className="dt-fav-meta">
                            {t(favoriteLabel(itemKind))}
                            {!collection && <> · {item.collection.name}</>}
                            {item.created_at ? (
                              <> · {formatRelativeTime(item.created_at, i18n.language)}</>
                            ) : null}
                          </span>
                        </span>
                      </label>
                      <button
                        type="button"
                        className="dt-fav-preview-toggle"
                        aria-expanded={open}
                        onClick={() => setPreview(open ? '' : key)}
                      >
                        {t(open ? 'Hide' : 'Preview')}
                        <ChevronDown size={13} className={open ? 'rotate-180' : ''} />
                      </button>
                    </div>
                    {open && (
                      <div className="dt-fav-preview">
                        <FavoriteContent
                          type={item.type}
                          markdown={item.output}
                          metadata={item.metadata}
                        />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        </div>
        <footer className="dt-fav-picker-foot">
          <span className="dt-fav-selection" aria-live="polite">
            {chosen.length ? (
              <>
                {t('{{count}} selected', { count: chosen.length })}
                {chosen.length > 1 && (
                  <span className="dt-fav-hint">
                    {' '}
                    · {t('Inserted in the order you picked them')}
                  </span>
                )}
                <button type="button" onClick={() => setPicked([])}>
                  {t('Clear')}
                </button>
              </>
            ) : (
              <span className="dt-fav-hint">
                {t('Pick one or more favorites to place on this page.')}
              </span>
            )}
          </span>
          <button type="button" className="dt-fav-button" onClick={onClose}>
            {t('Cancel')}
          </button>
          <button
            type="button"
            className="dt-fav-button"
            disabled={loading || !chosen.length}
            onClick={synthesize}
          >
            <Sparkles size={14} strokeWidth={1.8} />
            {t('Organize into a note')}
          </button>
          <button
            type="button"
            className="dt-fav-button is-primary"
            disabled={loading || !chosen.length}
            onClick={insert}
          >
            {chosen.length > 1 ? t('Insert {{count}}', { count: chosen.length }) : t('Insert')}
          </button>
        </footer>
      </div>
    </PickerShell>
  )
}

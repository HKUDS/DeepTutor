'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ChevronDown, PenLine, Plus, Search, type LucideIcon } from 'lucide-react'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import { formatRelativeTime } from '@/lib/relative-time'
import type { PageEntry, PageSection } from '@/components/sidebar/page-sections'

/**
 * The top-left of every page reads 「feature / one use of it」: the feature
 * as a soft chip that opens onto the other features of its shelf, and the
 * open session, document or folder as plain text beside it that opens onto
 * the others of its kind. The page bar hosts them; views with a toolbar of
 * their own (the reader) host the same pieces there.
 */

/** The feature: opens onto every feature of the sidebar shelf it lives on. */
export function FeatureCrumb({ section, page }: { section: PageSection; page: PageEntry }) {
  const [open, setOpen] = useState(false)
  const rootRef = useMenuPopover<HTMLDivElement>(open, setOpen)
  return (
    <div ref={rootRef} className="relative min-w-0 shrink-0">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(value => !value)}
        className="dt-crumb is-feature"
      >
        <page.icon size={16} strokeWidth={1.6} className="shrink-0 opacity-75" />
        <span className="truncate">{page.label}</span>
      </button>
      {open && (
        <div role="menu" aria-label={section.label} className="dt-popover dt-crumb-panel">
          <div className="dt-menu-label">{section.label}</div>
          {section.pages.map(entry => (
            <Link
              key={entry.href}
              role="menuitem"
              href={entry.href}
              prefetch={false}
              aria-current={entry.href === page.href ? 'page' : undefined}
              onClick={() => setOpen(false)}
              className="dt-menu-item"
            >
              <entry.icon size={16} strokeWidth={1.6} />
              <span className="min-w-0 flex-1 truncate">{entry.label}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export interface CrumbItem {
  id: string
  label: string
  href?: string
  /** Seconds since the epoch, shown as a relative time at the row's end. */
  updatedAt?: number
  /** Short text at the row's end when there is no time to show. */
  detail?: string
  icon?: LucideIcon
  /** A colour dot in front of the label (folders carry one). */
  color?: string
}

/** Rows a switcher shows before it asks for a search. */
const VISIBLE_ROWS = 60

/**
 * One use of the feature — a conversation, a document, a folder. Clicking
 * opens the others of its kind (fetched when opened, newest first), a way
 * to start a new one and a way to see them all; renaming, when the page
 * allows it, is in the menu and on double-click.
 */
export function InstanceCrumb({
  label,
  icon: Icon,
  color,
  menuLabel,
  currentId,
  load,
  search,
  create,
  all,
  onSelect,
  onRename,
  lead,
  trail,
  separator = true,
  placeholder = false,
}: {
  label: ReactNode
  icon?: LucideIcon
  color?: string
  /** Drawn in front of the label instead of the icon or dot (an avatar). */
  lead?: ReactNode
  /** Drawn right after the label (a status mark). */
  trail?: ReactNode
  /** Names the list for assistive technology and heads it. */
  menuLabel: string
  currentId?: string | null
  load: () => Promise<CrumbItem[]>
  /** Server-side search; without it the loaded rows are filtered in place. */
  search?: (query: string, signal: AbortSignal) => Promise<CrumbItem[]>
  create?: { label: string; href?: string; onSelect?: () => void }
  all?: { label: string; href: string }
  /** Items without an href are handed here. */
  onSelect?: (item: CrumbItem) => void
  onRename?: () => void
  separator?: boolean
  /** The label is a stand-in (an unnamed draft): drawn quieter. */
  placeholder?: boolean
}) {
  const { t, i18n } = useTranslation()
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<CrumbItem[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<CrumbItem[] | null>(null)
  const rootRef = useMenuPopover<HTMLDivElement>(open, setOpen)
  const inputRef = useRef<HTMLInputElement>(null)
  const request = useRef(0)

  // Fresh on every open: the list is only worth anything if it is current.
  const toggle = () => {
    if (open) return setOpen(false)
    const id = ++request.current
    setFailed(false)
    setQuery('')
    setFound(null)
    setOpen(true)
    load()
      .then(rows => request.current === id && setItems(rows))
      .catch(() => request.current === id && setFailed(true))
  }

  const trimmed = query.trim()
  useEffect(() => {
    // An empty query shows the loaded rows; a stale `found` is never read.
    if (!search || !trimmed) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      search(trimmed, controller.signal)
        .then(rows => setFound(rows))
        .catch(() => undefined)
    }, 180)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [search, trimmed])

  const rows = useMemo(() => {
    if (!items) return null
    if (!trimmed) return items.slice(0, VISIBLE_ROWS)
    if (search) return found
    const needle = trimmed.toLowerCase()
    return items.filter(item => item.label.toLowerCase().includes(needle)).slice(0, VISIBLE_ROWS)
  }, [found, items, search, trimmed])
  const searchable = Boolean(search) || (items?.length ?? 0) > 7
  // Typing is the fastest way through a long list; arrows still reach rows.
  useEffect(() => {
    if (open && searchable) inputRef.current?.focus()
  }, [open, searchable])

  const choose = useCallback(
    (item: CrumbItem) => {
      setOpen(false)
      if (item.href) router.push(item.href)
      else onSelect?.(item)
    },
    [onSelect, router]
  )

  return (
    <>
      {separator && (
        <span aria-hidden className="dt-crumb-sep">
          /
        </span>
      )}
      <div ref={rootRef} className="relative min-w-0">
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={toggle}
          onDoubleClick={onRename ? () => (setOpen(false), onRename()) : undefined}
          className={`dt-crumb is-instance${placeholder ? ' is-placeholder' : ''}`}
        >
          {lead ??
            (color ? (
              <span aria-hidden className="dt-crumb-dot" style={{ background: color }} />
            ) : Icon ? (
              <Icon size={15} strokeWidth={1.6} className="shrink-0 opacity-70" />
            ) : null)}
          <span className="truncate">{label}</span>
          {trail}
          <ChevronDown size={13} strokeWidth={1.8} aria-hidden className="dt-crumb-caret" />
        </button>
        {open && (
          <div role="menu" aria-label={menuLabel} className="dt-popover dt-crumb-panel is-instances">
            {searchable && (
              <label className="dt-crumb-search">
                <Search size={14} strokeWidth={1.7} aria-hidden />
                <input
                  ref={inputRef}
                  value={query}
                  onChange={event => setQuery(event.target.value)}
                  placeholder={t('Search')}
                  aria-label={t('Search')}
                />
              </label>
            )}
            {create &&
              (create.href ? (
                <Link
                  role="menuitem"
                  href={create.href}
                  prefetch={false}
                  onClick={() => setOpen(false)}
                  className="dt-menu-item"
                >
                  <Plus size={16} strokeWidth={1.6} />
                  <span className="min-w-0 flex-1 truncate">{create.label}</span>
                </Link>
              ) : (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => (setOpen(false), create.onSelect?.())}
                  className="dt-menu-item"
                >
                  <Plus size={16} strokeWidth={1.6} />
                  <span className="min-w-0 flex-1 truncate">{create.label}</span>
                </button>
              ))}
            <div className="dt-menu-label">{menuLabel}</div>
            <div className="dt-crumb-rows">
              {rows === null ? (
                <div className="dt-crumb-empty">{failed ? t('Failed to load') : t('Loading...')}</div>
              ) : rows.length === 0 ? (
                <div className="dt-crumb-empty">{trimmed ? t('No matches') : t('Nothing here yet')}</div>
              ) : (
                rows.map(item => {
                  const current = item.id === currentId
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="menuitem"
                      aria-current={current ? 'page' : undefined}
                      onClick={() => choose(item)}
                      className="dt-menu-item"
                    >
                      {item.color ? (
                        <span aria-hidden className="dt-crumb-dot" style={{ background: item.color }} />
                      ) : item.icon ? (
                        <item.icon size={15} strokeWidth={1.6} />
                      ) : null}
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      {current ? (
                        <Check size={14} strokeWidth={1.8} className="dt-crumb-check" />
                      ) : item.updatedAt ? (
                        <span className="dt-crumb-detail">{formatRelativeTime(item.updatedAt, i18n.language)}</span>
                      ) : item.detail ? (
                        <span className="dt-crumb-detail">{item.detail}</span>
                      ) : null}
                    </button>
                  )
                })
              )}
            </div>
            {(all || onRename) && <div className="dt-menu-divider" />}
            {onRename && (
              <button
                type="button"
                role="menuitem"
                onClick={() => (setOpen(false), onRename())}
                className="dt-menu-item is-quiet"
              >
                <PenLine size={15} strokeWidth={1.6} />
                <span className="min-w-0 flex-1 truncate">{t('Rename')}</span>
              </button>
            )}
            {all && (
              <Link
                role="menuitem"
                href={all.href}
                prefetch={false}
                onClick={() => setOpen(false)}
                className="dt-menu-item is-quiet"
              >
                <span className="min-w-0 flex-1 truncate">{all.label}</span>
              </Link>
            )}
          </div>
        )}
      </div>
    </>
  )
}

/**
 * An instance crumb being renamed in place: same box, an input instead of
 * the label. Enter commits, Escape cancels, leaving commits.
 */
export function CrumbRename({
  value,
  onChange,
  onCommit,
  onCancel,
  disabled,
  label,
  maxLength = 100,
}: {
  value: string
  onChange: (value: string) => void
  onCommit: () => void
  onCancel: () => void
  disabled?: boolean
  label: string
  maxLength?: number
}) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    ref.current?.focus()
    ref.current?.select()
  }, [])
  return (
    <>
      <span aria-hidden className="dt-crumb-sep">
        /
      </span>
      <input
        ref={ref}
        value={value}
        onChange={event => onChange(event.target.value)}
        onBlur={onCommit}
        onKeyDown={event => {
          if (event.key === 'Enter') {
            event.preventDefault()
            onCommit()
          } else if (event.key === 'Escape') {
            event.preventDefault()
            onCancel()
          }
        }}
        disabled={disabled}
        aria-label={label}
        maxLength={maxLength}
        size={Math.max(8, Math.min(48, value.length + 2))}
        className="dt-crumb-input"
      />
    </>
  )
}

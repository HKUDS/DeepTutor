'use client'

import { useState, type MouseEvent } from 'react'
import Link from 'next/link'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  Bookmark,
  Check,
  ChevronRight,
  CornerUpRight,
  FileDown,
  FileText,
  MoreHorizontal,
  PanelLeft,
  Pin,
  PinOff,
  Sparkles,
} from 'lucide-react'
import Tooltip from '@/shared/ui/Tooltip'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import { FeatureCrumb, InstanceCrumb } from '@/components/layout/LocationCrumbs'
import { useShelfFeature } from '@/components/sidebar/PageBar'
import type { NotePage, NoteSummary } from '@/lib/notes-api'

export type NoteSaveStatus = 'Saved' | 'Saving…' | 'Unsaved changes' | 'Save failed'

function Crumb({
  page,
  onNavigate,
}: {
  page: Pick<NoteSummary, 'id' | 'title' | 'icon'>
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, id: string) => void
}) {
  const { t } = useTranslation()
  return (
    <Link
      href={`/co-writer/${page.id}`}
      className="dt-note-crumb"
      onClick={event => onNavigate(event, page.id)}
    >
      {page.icon && <span aria-hidden>{page.icon}</span>}
      <span className="truncate">{page.title || t('Untitled')}</span>
    </Link>
  )
}

export default function NoteTopBar({
  page,
  pages,
  invalidParents,
  status,
  busy,
  embedded,
  treeOpen,
  companionOpen,
  onToggleTree,
  onToggleCompanion,
  onNavigate,
  onOpenPage,
  onCreatePage,
  onMetadata,
  onInsertFavorite,
  onExport,
}: {
  page: NotePage | null
  pages: NoteSummary[]
  invalidParents: Set<string>
  status: NoteSaveStatus
  busy: boolean
  embedded: boolean
  treeOpen: boolean
  companionOpen: boolean
  onToggleTree: () => void
  onToggleCompanion: () => void
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, id: string) => void
  /** Opens another page from the page switcher, saving this one first. */
  onOpenPage: (id: string) => void
  onCreatePage: () => void
  onMetadata: (patch: Partial<NotePage>) => void
  onInsertFavorite: () => void
  onExport: (format: 'md' | 'docx') => void
}) {
  const { t } = useTranslation()
  const feature = useShelfFeature('/co-writer')
  const [open, setOpenState] = useState(false)
  const [moving, setMoving] = useState(false)
  const [query, setQuery] = useState('')
  const setOpen = (value: boolean | ((current: boolean) => boolean)) => {
    const next = typeof value === 'function' ? value(open) : value
    setOpenState(next)
    if (!next) {
      setMoving(false)
      setQuery('')
    }
  }
  const menu = useMenuPopover<HTMLDivElement>(open, setOpen)
  const byId = new Map(pages.map(p => [p.id, p]))
  const ancestors: NoteSummary[] = []
  for (
    let parent = page?.parent_id ? byId.get(page.parent_id) : undefined, guard = 0;
    parent && guard < 12;
    parent = parent.parent_id ? byId.get(parent.parent_id) : undefined, guard++
  )
    ancestors.unshift(parent)
  // Deep pages keep their first and last ancestor; the middle folds away.
  const shown = ancestors.length > 2 ? [ancestors[0], null, ancestors.at(-1)!] : ancestors
  const targets = pages
    .filter(p => p.id !== page?.id && !invalidParents.has(p.id))
    .filter(p => (p.title || '').toLowerCase().includes(query.trim().toLowerCase()))
  const move = (parent_id: string | null) => {
    setOpen(false)
    onMetadata({ parent_id })
  }
  return (
    <header className="dt-note-topbar">
      <Tooltip label={t(treeOpen ? 'Hide pages' : 'Show pages')} side="bottom">
        <button
          className="dt-note-icon-button"
          aria-label={t('Page tree')}
          aria-expanded={treeOpen}
          aria-controls="note-page-tree"
          onClick={onToggleTree}
        >
          <PanelLeft size={16} strokeWidth={1.7} />
        </button>
      </Tooltip>
      {/* 「笔记本 / … / this page」: the feature opens onto the home shelf,
          the page onto every other page of the notebook. */}
      <nav className="dt-note-breadcrumb" aria-label={t('Breadcrumb')}>
        {!embedded && feature && (
          <span className="dt-note-feature">
            <FeatureCrumb section={feature.section} page={feature.page} />
          </span>
        )}
        {shown.map((ancestor, i) => (
          <span key={ancestor?.id ?? `gap-${i}`} className="contents">
            {(i > 0 || (!embedded && feature)) && (
              <span aria-hidden className="dt-crumb-sep">
                /
              </span>
            )}
            {ancestor ? (
              <Crumb page={ancestor} onNavigate={onNavigate} />
            ) : (
              <span className="dt-note-crumb is-gap">…</span>
            )}
          </span>
        ))}
        {page && (
          <span className="dt-note-current" aria-current="page">
            <InstanceCrumb
              label={
                <>
                  {page.icon && <span aria-hidden>{page.icon} </span>}
                  {page.title || t('Untitled')}
                </>
              }
              separator={shown.length > 0 || (!embedded && Boolean(feature))}
              menuLabel={t('Notebook pages')}
              currentId={page.id}
              load={async () =>
                [...pages]
                  .sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0))
                  .map(entry => ({
                    id: entry.id,
                    label: `${entry.icon ? `${entry.icon} ` : ''}${entry.title || t('Untitled')}`,
                    updatedAt: entry.updated_at,
                  }))
              }
              onSelect={item => onOpenPage(item.id)}
              create={{ label: t('New page'), onSelect: onCreatePage }}
              all={embedded ? undefined : { label: t('All pages'), href: '/co-writer' }}
            />
            {page.pinned && <Pin size={11} className="shrink-0 opacity-50" aria-label={t('Pinned page')} />}
          </span>
        )}
      </nav>
      <span
        className={`dt-note-status ${status === 'Save failed' ? 'is-error' : ''} ${status === 'Saved' ? 'is-idle' : ''}`}
        role="status"
      >
        {t(status)}
      </span>
      <button
        className={`dt-note-ask ${companionOpen ? 'is-active' : ''}`}
        aria-pressed={companionOpen}
        onClick={onToggleCompanion}
      >
        <Sparkles size={14} strokeWidth={1.8} />
        {t('Ask Dito')}
      </button>
      <div ref={menu} className="relative">
        <Tooltip label={t('More')} side="bottom" suppressed={open}>
          <button
            className="dt-note-icon-button"
            aria-label={t('More page actions')}
            aria-haspopup="menu"
            aria-expanded={open}
            disabled={!page}
            onClick={() => setOpen(!open)}
          >
            <MoreHorizontal size={16} strokeWidth={1.7} />
          </button>
        </Tooltip>
        {open && page && (
          <div className="dt-popover dt-note-page-menu" role="menu">
            {moving ? (
              <>
                <button role="menuitem" className="dt-menu-item is-quiet" onClick={() => setMoving(false)}>
                  <ArrowLeft size={14} />
                  {t('Move to')}
                </button>
                <input
                  className="dt-note-menu-search"
                  aria-label={t('Search pages')}
                  placeholder={t('Search pages…')}
                  value={query}
                  autoFocus
                  onChange={e => setQuery(e.target.value)}
                />
                <div className="dt-note-move-list">
                  {!query.trim() && (
                    <button
                      role="menuitem"
                      className="dt-menu-item"
                      disabled={busy}
                      onClick={() => move(null)}
                    >
                      <FileText size={14} />
                      <span className="flex-1 truncate">{t('Top level')}</span>
                      {!page.parent_id && <Check size={14} />}
                    </button>
                  )}
                  {targets.map(target => (
                    <button
                      key={target.id}
                      role="menuitem"
                      className="dt-menu-item"
                      disabled={busy}
                      onClick={() => move(target.id)}
                    >
                      <span className="dt-note-menu-glyph" aria-hidden>
                        {target.icon || <FileText size={14} />}
                      </span>
                      <span className="flex-1 truncate">{target.title || t('Untitled')}</span>
                      {page.parent_id === target.id && <Check size={14} />}
                    </button>
                  ))}
                  {!targets.length && query.trim() && (
                    <p className="dt-note-menu-empty">{t('No matching pages')}</p>
                  )}
                </div>
              </>
            ) : (
              <>
                <button
                  role="menuitem"
                  className="dt-menu-item"
                  disabled={busy}
                  onClick={() => {
                    setOpen(false)
                    onMetadata({ pinned: !page.pinned })
                  }}
                >
                  {page.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                  {t(page.pinned ? 'Unpin' : 'Pin to top')}
                </button>
                <button
                  role="menuitem"
                  className="dt-menu-item"
                  disabled={busy}
                  onClick={() => setMoving(true)}
                >
                  <CornerUpRight size={14} />
                  <span className="flex-1">{t('Move to')}</span>
                  <ChevronRight size={13} className="opacity-50" />
                </button>
                <button
                  role="menuitem"
                  className="dt-menu-item"
                  onClick={() => {
                    setOpen(false)
                    onInsertFavorite()
                  }}
                >
                  <Bookmark size={14} />
                  {t('Insert favorite')}
                </button>
                <div className="dt-menu-divider" />
                <button
                  role="menuitem"
                  className="dt-menu-item"
                  onClick={() => {
                    setOpen(false)
                    onExport('md')
                  }}
                >
                  <FileDown size={14} />
                  {t('Export Markdown')}
                </button>
                <button
                  role="menuitem"
                  className="dt-menu-item"
                  onClick={() => {
                    setOpen(false)
                    onExport('docx')
                  }}
                >
                  <FileDown size={14} />
                  <span className="flex-1">{t('Export Word')}</span>
                </button>
                <p className="dt-note-menu-note">
                  {t('Word export keeps text and source links; interactive blocks become static.')}
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </header>
  )
}

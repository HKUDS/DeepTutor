'use client'

import dynamic from 'next/dynamic'

import { useCallback, useMemo, useState, type MouseEvent } from 'react'
import Link from 'next/link'
import { ChevronRight, FileText, MoreHorizontal, Pin, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import type { NoteTreeView } from './useNoteNavigation'
import type { NoteSummary } from '@/lib/notes-api'

const TreeMenu = dynamic(() => import('./NotePageActions').then(module => module.TreeMenu), {
  ssr: false,
})

export default function NotePageTree({
  pages,
  currentId,
  getView,
  onViewChange,
  busy,
  embedded = false,
  onNavigate,
  onCreate,
  onDelete,
  onPin,
}: {
  pages: NoteSummary[]
  currentId: string
  getView?: () => NoteTreeView
  onViewChange?: (patch: Partial<NoteTreeView>) => void
  busy: boolean
  embedded?: boolean
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, id: string) => void
  onClose?: () => void
  onCreate: (parentId: string | null) => void
  onDelete: (page: NoteSummary) => void
  onPin?: (page: NoteSummary) => void
}) {
  const { t } = useTranslation()
  const [view] = useState(() => getView?.())
  const [collapsed, setCollapsed] = useState(() => view?.collapsed ?? new Set<string>())
  const restoreScroll = useCallback((node: HTMLDivElement | null) => {
    if (node && view) node.scrollTop = view.scrollTop
  }, [view])
  const [menu, setMenu] = useState<{
    id: string
    trigger: HTMLButtonElement
  } | null>(null)
  const closeMenu = useCallback(() => setMenu(null), [])
  const childrenByParent = useMemo(() => {
    const groups = new Map<string | null, NoteSummary[]>()
    for (const page of pages) {
      const siblings = groups.get(page.parent_id)
      if (siblings) siblings.push(page)
      else groups.set(page.parent_id, [page])
    }
    for (const siblings of groups.values()) {
      siblings.sort((a, b) => Number(b.pinned) - Number(a.pinned))
    }
    return groups
  }, [pages])
  const rows = (parent: string | null, depth: number): React.ReactNode => {
    const children = childrenByParent.get(parent)
    if (!children) return null
    return (
      <ul className={parent ? 'dt-note-tree-children' : 'dt-note-tree-roots'}>
        {children.map(page => {
          const title = page.title || t('Untitled')
          const hasChildren = childrenByParent.has(page.id)
          const expanded = !collapsed.has(page.id)
          return (
            <li key={page.id}>
              <div
                className={`dt-note-tree-row ${page.pinned ? 'is-pinned' : ''} ${page.id === currentId ? 'is-current' : ''}`}
                style={{ paddingLeft: depth * 14 }}
                onContextMenu={event => {
                  event.preventDefault()
                  if (busy) return
                  const trigger =
                    event.currentTarget.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!
                  setMenu({ id: page.id, trigger })
                }}
              >
                {hasChildren ? (
                  <button
                    className="dt-note-tree-toggle"
                    aria-label={t(expanded ? 'Collapse {{page}}' : 'Expand {{page}}', {
                      page: title,
                    })}
                    aria-expanded={expanded}
                    onClick={() => {
                      const next = new Set(collapsed)
                      if (expanded) next.add(page.id)
                      else next.delete(page.id)
                      onViewChange?.({ collapsed: next })
                      setCollapsed(next)
                    }}
                  >
                    <ChevronRight size={13} className={expanded ? 'rotate-90' : ''} />
                  </button>
                ) : (
                  <span className="dt-note-tree-toggle" />
                )}
                <Link
                  href={`/co-writer/${page.id}`}
                  onClick={event => onNavigate(event, page.id)}
                  aria-current={page.id === currentId ? 'page' : undefined}
                >
                  <span className="dt-note-tree-icon" aria-hidden>
                    {page.icon || <FileText size={15} strokeWidth={1.6} />}
                  </span>
                  <span className="truncate">{title}</span>
                </Link>
                {page.pinned && (
                  <Tooltip label={t('Unpin')}>
                    <button
                      type="button"
                      className="dt-note-tree-add dt-note-tree-unpin"
                      aria-label={t('Unpin')}
                      disabled={busy || !onPin}
                      onClick={() => onPin?.(page)}
                    >
                      <Pin size={14} fill="currentColor" strokeWidth={2.5} aria-hidden />
                    </button>
                  </Tooltip>
                )}
                <Tooltip label={t('Add a page inside')}>
                  <button
                    className="dt-note-tree-add"
                    aria-label={t('Add a page inside {{page}}', { page: title })}
                    disabled={busy}
                    onClick={() => onCreate(page.id)}
                  >
                    <Plus size={14} />
                  </button>
                </Tooltip>
                <button
                  className="dt-note-tree-add"
                  aria-label={t('Page actions for {{page}}', { page: title })}
                  aria-haspopup="menu"
                  aria-expanded={menu?.id === page.id}
                  disabled={busy}
                  onClick={event => {
                    const trigger = event.currentTarget
                    setMenu(
                      menu?.id === page.id
                        ? null
                        : { id: page.id, trigger }
                    )
                  }}
                >
                  <MoreHorizontal size={14} />
                </button>
              </div>
              {menu?.id === page.id && (
                <TreeMenu
                  trigger={menu.trigger}
                  onClose={closeMenu}
                  page={page}
                  hasChildren={hasChildren}
                  pinned={page.pinned}
                  onPin={onPin && (() => {
                    closeMenu()
                    onPin(page)
                  })}
                  onDelete={() => {
                    closeMenu()
                    onDelete(page)
                  }}
                />
              )}
              {expanded && hasChildren && rows(page.id, depth + 1)}
            </li>
          )
        })}
      </ul>
    )
  }
  return (
    <nav id="note-page-tree" className="dt-note-page-tree" aria-label={t('Page tree')}>
      <div className="dt-note-tree-heading">
        {embedded ? (
          <span>{t('Learning notebook')}</span>
        ) : (
          <Link href="/co-writer">{t('Learning notebook')}</Link>
        )}
        <Tooltip label={t('New page')}>
          <button
            className="dt-note-icon-button"
            aria-label={t('New page')}
            disabled={busy}
            onClick={() => onCreate(null)}
          >
            <Plus size={15} />
          </button>
        </Tooltip>
      </div>
      <div
        className="dt-note-tree-scroll"
        ref={restoreScroll}
        onScroll={event => {
          onViewChange?.({ scrollTop: event.currentTarget.scrollTop })
          closeMenu()
        }}
      >
        {rows(null, 0)}
      </div>
    </nav>
  )
}

'use client'

import dynamic from 'next/dynamic'

import { useCallback, useState, type MouseEvent } from 'react'
import Link from 'next/link'
import { ChevronRight, FileText, MoreHorizontal, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import type { NoteSummary } from '@/lib/notes-api'

const TreeMenu = dynamic(() => import('./NotePageActions').then(module => module.TreeMenu), {
  ssr: false,
})

export default function NotePageTree({
  pages,
  currentId,
  busy,
  embedded = false,
  onNavigate,
  onCreate,
  onDelete,
}: {
  pages: NoteSummary[]
  currentId: string
  busy: boolean
  embedded?: boolean
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, id: string) => void
  onClose?: () => void
  onCreate: (parentId: string | null) => void
  onDelete: (page: NoteSummary) => void
}) {
  const { t } = useTranslation()
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())
  const [menu, setMenu] = useState<{
    id: string
    trigger: HTMLButtonElement
    anchor: DOMRect
  } | null>(null)
  const closeMenu = useCallback(() => setMenu(null), [])
  const rows = (parent: string | null, depth: number, ancestors = new Set<string>()): React.ReactNode => {
    const children = pages
      .filter(p => p.parent_id === parent && !ancestors.has(p.id))
      .sort((a, b) => Number(b.pinned) - Number(a.pinned))
    if (!children.length) return null
    return (
      <ul className={parent ? 'dt-note-tree-children' : 'dt-note-tree-roots'}>
        {children.map(page => {
          const title = page.title || t('Untitled')
          const hasChildren = pages.some(p => p.parent_id === page.id)
          const expanded = !collapsed.has(page.id)
          return (
            <li key={page.id}>
              <div
                className={`dt-note-tree-row ${page.id === currentId ? 'is-current' : ''}`}
                style={{ paddingLeft: depth * 14 }}
                onContextMenu={event => {
                  event.preventDefault()
                  if (busy) return
                  const trigger =
                    event.currentTarget.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!
                  const anchor =
                    event.clientX || event.clientY
                      ? new DOMRect(event.clientX, event.clientY, 0, 0)
                      : trigger.getBoundingClientRect()
                  setMenu({ id: page.id, trigger, anchor })
                }}
              >
                {hasChildren ? (
                  <button
                    className="dt-note-tree-toggle"
                    aria-label={t(expanded ? 'Collapse {{page}}' : 'Expand {{page}}', {
                      page: title,
                    })}
                    aria-expanded={expanded}
                    onClick={() =>
                      setCollapsed(previous => {
                        const next = new Set(previous)
                        if (expanded) next.add(page.id)
                        else next.delete(page.id)
                        return next
                      })
                    }
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
                        : {
                            id: page.id,
                            trigger,
                            anchor: trigger.getBoundingClientRect(),
                          }
                    )
                  }}
                >
                  <MoreHorizontal size={14} />
                </button>
              </div>
              {menu?.id === page.id && (
                <TreeMenu
                  anchor={menu.anchor}
                  trigger={menu.trigger}
                  onClose={closeMenu}
                  page={page}
                  hasChildren={hasChildren}
                  onDelete={() => {
                    closeMenu()
                    onDelete(page)
                  }}
                />
              )}
              {expanded && rows(page.id, depth + 1, new Set([...ancestors, page.id]))}
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
      <div className="dt-note-tree-scroll" onScroll={closeMenu}>
        {rows(null, 0)}
      </div>
    </nav>
  )
}

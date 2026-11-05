'use client'

import { CalendarDays } from 'lucide-react'

import { createPortal } from 'react-dom'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { Columns3, CornerDownLeft, MessageCircle, PenLine, Search, Settings, Users, type LucideIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import PartnerAvatar from '@/components/partners/PartnerAvatar'
import { DASHBOARD_GROUPS, PERSONALIZATION_GROUPS, visibleGroups } from '@/components/space/dashboard-groups'
import { useCapabilityFilter } from '@/features/capabilities/useCapabilityCatalog'
import { useLearningIndex } from '@/hooks/useLearningIndex'
import { usePartnerNavigation } from '@/hooks/usePartnerNavigation'
import { allLearningActivity } from '@/lib/learning-dashboard'
import { navigateTask } from '@/lib/workspace-scope'
import type { SessionSummary } from '@/lib/session-api'
import { isNoteSession } from '@/lib/mastery-session'
import { learningSurface } from '@/components/learning/surfaces'
import { navVisibleUnderPolicy } from './nav-entries'

interface PaletteItem {
  id: string
  label: string
  detail?: string
  icon: ReactNode
  run: () => void
}
interface PaletteGroup {
  title: string
  items: PaletteItem[]
}

const glyph = (Icon: LucideIcon) => <Icon size={16} strokeWidth={1.6} />
const includes = (text: string, query: string) => text.toLocaleLowerCase().includes(query)

/**
 * ⌘K: one field that finds anything the sidebar holds — places, conversations,
 * learning, partners — and opens it. It reads the same sources as the sidebar
 * shelves (all client-cached), so opening it costs no extra round trip.
 */
export function CommandPalette({
  open,
  onClose,
  categories,
  allowedSurfaces,
  sessions,
  onSelectSession,
  onNewChat,
}: {
  open: boolean
  onClose: () => void
  categories: readonly { id: string; label: string; icon: LucideIcon; href: string }[]
  allowedSurfaces: string[] | null
  sessions: SessionSummary[]
  onSelectSession?: (sessionId: string) => void | Promise<void>
  onNewChat: () => void
}) {
  const { t, i18n } = useTranslation()
  const router = useRouter()
  const zh = i18n.language.startsWith('zh')
  const available = useCapabilityFilter()
  const { sources } = useLearningIndex(open)
  const { data: partnerData } = usePartnerNavigation(open)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const restoreFocus = useRef<HTMLElement | null>(null)

  // The shell mounts the palette per opening, so query and selection start fresh.
  useEffect(() => {
    if (!open) return
    restoreFocus.current = document.activeElement as HTMLElement | null
    requestAnimationFrame(() => inputRef.current?.focus())
    return () => restoreFocus.current?.focus?.()
  }, [open])

  const groups = useMemo<PaletteGroup[]>(() => {
    const go = (href: string) => () => navigateTask(href, router.push)
    const q = query.trim().toLocaleLowerCase()
    const places: PaletteItem[] = [
      { id: 'new-chat', label: t('navigation.newChat'), icon: glyph(PenLine), run: onNewChat },
      ...categories.map(item => ({ id: `category:${item.id}`, label: t(item.label), icon: glyph(item.icon), run: go(item.href) })),
      ...[
        { href: '/calendar', label: 'Calendar', icon: CalendarDays },
              { href: '/kanban', label: 'Task Board', icon: Columns3 },
        { href: '/co-writer', label: 'Co-Writer', icon: PenLine },
      ]
        .filter(item => navVisibleUnderPolicy(item.href, allowedSurfaces))
        .map(item => ({ id: item.href, label: t(item.label), icon: glyph(item.icon), run: go(item.href) })),
      ...[
        { groups: DASHBOARD_GROUPS, detail: t('navigation.resources') },
        { groups: PERSONALIZATION_GROUPS, detail: t('navigation.personalization') },
      ].flatMap(({ groups, detail }) =>
        visibleGroups(groups, available).flatMap(group =>
          group.items
            .filter(row => row.href !== '/agents' || navVisibleUnderPolicy(row.href, allowedSurfaces))
            .map(row => ({
              id: `resource:${row.key}`,
              label: zh ? row.title.zh : row.title.en,
              detail,
              icon: glyph(row.icon),
              run: go(row.href),
            }))
        )
      ),
      { id: 'settings', label: t('Settings'), icon: glyph(Settings), run: go('/settings') },
    ]
    const conversations: PaletteItem[] = sessions
      .filter(
        session =>
          !session.preferences?.archived &&
          !session.preferences?.parent_session_id &&
          !isNoteSession(session)
      )
      .map(session => ({
        id: `session:${session.session_id}`,
        label: session.title || t('New conversation'),
        icon: glyph(MessageCircle),
        run: () => void (onSelectSession ? onSelectSession(session.session_id) : go(`/chat/${session.session_id}`)()),
      }))
    const learning: PaletteItem[] = allLearningActivity(sources).map(item => {
      const surface = learningSurface(item.kind)
      return {
        id: `learning:${item.key}`,
        label: item.title,
        detail: t(surface.title),
        icon: glyph(surface.icon),
        run: go(item.href),
      }
    })
    const partners: PaletteItem[] = [
      ...partnerData.partners.map(partner => ({
        id: `partner:${partner.partner_id}`,
        label: partner.name,
        icon: <PartnerAvatar name={partner.name} emoji={partner.emoji} image={partner.avatar} color={partner.color} size={18} />,
        run: go(`/partners/${encodeURIComponent(partner.partner_id)}`),
      })),
      ...partnerData.groups.map(group => ({
        id: `group:${group.group_id}`,
        label: group.name,
        detail: t('Groups'),
        icon: glyph(Users),
        run: go(`/partners/groups/${encodeURIComponent(group.group_id)}`),
      })),
    ]
    const pick = (items: PaletteItem[], idle: number) =>
      q ? items.filter(item => includes(`${item.label} ${item.detail ?? ''}`, q)).slice(0, 6) : items.slice(0, idle)
    return [
      { title: t('navigation.jumpTo'), items: pick(places, 1 + categories.length + 2) },
      { title: t('Conversations'), items: pick(conversations, 5) },
      { title: t('navigation.learning'), items: pick(learning, q ? 6 : 0) },
      { title: t('navigation.partners'), items: pick(partners, q ? 6 : 0) },
    ].filter(group => group.items.length > 0)
  }, [query, categories, allowedSurfaces, available, zh, sessions, sources, partnerData, onSelectSession, onNewChat, router.push, t])

  const flat = groups.flatMap(group => group.items)
  const current = Math.min(activeIndex, Math.max(0, flat.length - 1))

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${current}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [current])

  if (!open || typeof document === 'undefined') return null

  const run = (item: PaletteItem | undefined) => {
    if (!item) return
    onClose()
    item.run()
  }
  let index = -1
  return createPortal(
    <div className="dt-palette-backdrop" onPointerDown={event => event.target === event.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={t('navigation.searchEverything')} className="dt-palette">
        <div className="dt-palette-field">
          <Search size={17} strokeWidth={1.7} className="shrink-0 opacity-50" />
          <input
            ref={inputRef}
            value={query}
            role="combobox"
            aria-expanded
            aria-controls="dt-palette-results"
            aria-activedescendant={flat[current] ? `dt-palette-${current}` : undefined}
            placeholder={t('navigation.searchEverything')}
            onChange={event => {
              setQuery(event.target.value)
              setActiveIndex(0)
            }}
            onKeyDown={event => {
              if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault()
                const step = event.key === 'ArrowDown' ? 1 : -1
                setActiveIndex((current + step + flat.length) % Math.max(1, flat.length))
              } else if (event.key === 'Enter') {
                event.preventDefault()
                run(flat[current])
              } else if (event.key === 'Escape') {
                event.preventDefault()
                onClose()
              }
            }}
          />
        </div>
        <div ref={listRef} id="dt-palette-results" role="listbox" className="dt-palette-results">
          {groups.map(group => (
            <div key={group.title} role="group" aria-label={group.title}>
              <div className="dt-palette-group">{group.title}</div>
              {group.items.map(item => {
                index += 1
                const position = index
                return (
                  <div
                    key={item.id}
                    id={`dt-palette-${position}`}
                    data-index={position}
                    role="option"
                    aria-selected={position === current}
                    onPointerMove={() => position !== current && setActiveIndex(position)}
                    onClick={() => run(item)}
                    className="dt-palette-item"
                  >
                    <span className="dt-palette-icon">{item.icon}</span>
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.detail && <span className="dt-palette-detail">{item.detail}</span>}
                    {position === current && <CornerDownLeft size={14} strokeWidth={1.8} className="shrink-0 opacity-50" />}
                  </div>
                )
              })}
            </div>
          ))}
          {!flat.length && <p className="dt-palette-empty">{t('navigation.noResults')}</p>}
        </div>
        <div className="dt-palette-hints" aria-hidden>
          <span><kbd>↑</kbd><kbd>↓</kbd> {t('navigation.paletteSelect')}</span>
          <span><kbd>↵</kbd> {t('navigation.paletteOpen')}</span>
          <span><kbd>esc</kbd> {t('navigation.paletteClose')}</span>
        </div>
      </div>
    </div>,
    document.body
  )
}

import { LEARNING_HUB } from '@/lib/learning-routes'
import {
  Bot,
  GraduationCap,
  HeartHandshake,
  House,
  LayoutGrid,
  ListTodo,
  PenLine,
  Settings,
  type LucideIcon,
} from 'lucide-react'

import type { Capability } from '@/lib/capability-routes'

export interface NavEntry {
  href: string
  label: string
  icon: LucideIcon
  tooltipKey?: string
  defaultCollapsed?: boolean
  /** Model capability this feature needs; locked when the user lacks it. */
  requires?: Capability
  /**
   * Learning-account surfaces that may see this entry. Absent means the
   * entry is hidden whenever a learning policy is in effect (#1222).
   */
  surfaces?: readonly string[]
}

/**
 * The workspace features, in the order they ship in.
 *
 * This is the *default* arrangement, not the rendered one — a learner can
 * reorder these and fold the ones they don't use into "More"
 * (``lib/sidebar-layout.ts``). Adding an entry here places it for everyone,
 * including people who have already arranged their sidebar: it arrives next to
 * the neighbour it follows below rather than at the bottom of their list.
 */
export const PRIMARY_NAV: NavEntry[] = [
  {
    href: '/chat',
    label: 'Home',
    icon: House,
    tooltipKey: 'Home tooltip',
    requires: 'llm',
    surfaces: ['chat'],
  },
  {
    href: '/partners',
    label: 'Partners',
    icon: HeartHandshake,
    tooltipKey: 'Partners tooltip',
    requires: 'llm',
  },
  {
    href: LEARNING_HUB,
    label: 'Personalized Learning',
    icon: GraduationCap,
    tooltipKey: 'One tutor, your own way to learn.',
    surfaces: ['reading', 'chat', 'books'],
  },
  { href: '/space', label: 'Learning Space', icon: LayoutGrid, tooltipKey: 'Space tooltip' },
  {
    href: '/kanban',
    label: 'Task Board',
    icon: ListTodo,
    tooltipKey: 'kanban.intro',
    surfaces: ['chat'],
  },
  {
    href: '/co-writer',
    label: 'Co-Writer',
    icon: PenLine,
    tooltipKey: 'Co-Writer tooltip',
    requires: 'llm',
    defaultCollapsed: true,
  },
  {
    href: '/agents',
    label: 'My Agents',
    icon: Bot,
    tooltipKey: 'Agents tooltip',
    defaultCollapsed: true,
  },
]

export const SECONDARY_NAV: NavEntry[] = [{ href: '/settings', label: 'Settings', icon: Settings }]

export const DEFAULT_COLLAPSED_NAV = PRIMARY_NAV.filter(entry => entry.defaultCollapsed).map(
  entry => entry.href
)

export const PRIMARY_NAV_HREFS = PRIMARY_NAV.map(entry => entry.href)

export const NAV_BY_HREF = new Map(
  [...PRIMARY_NAV, ...SECONDARY_NAV].map(entry => [entry.href, entry])
)

export function isNavActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`)
}

/**
 * A learning policy hides every feature the account cannot call. Settings
 * stays, because the redacted page (theme, language) is still theirs.
 * ``allowedSurfaces === null`` means no policy: the full sidebar.
 */
export function navVisibleUnderPolicy(
  href: string,
  allowedSurfaces: readonly string[] | null,
): boolean {
  if (allowedSurfaces === null) return true
  if (href === '/settings') return true
  const surfaces = NAV_BY_HREF.get(href)?.surfaces
  if (!surfaces?.length) return false
  return surfaces.some(surface => allowedSurfaces.includes(surface))
}

import { Activity, Archive, BarChart3, Bot, Settings2 } from 'lucide-react'
import {
  SETTINGS_CATEGORIES,
  isSettingsCategoryVisible,
  isSettingsLeafVisible,
  resolveSettingsKey,
  type SettingsLeaf,
} from './settings-nav'
import type { LucideIcon } from 'lucide-react'
import type { SettingsAccess } from './settings-access'

export const SETTINGS_PAGE_GROUPS: { label: string; keys: string[] }[] = [
  { label: 'Personal', keys: ['general', 'workspace', 'data-migration', 'appearance', 'usage'] },
  {
    label: 'Models & services',
    keys: ['connections', 'llm', 'task-models', 'embedding', 'search', 'voice', 'multimodal'],
  },
  {
    label: 'Learning & conversation',
    keys: ['starters', 'attachments', 'video-learning', 'learner-profile', 'progress', 'guardian', 'memory'],
  },
  {
    label: 'Features & integrations',
    keys: ['tools', 'capabilities', 'agent-claude-code', 'knowledge'],
  },
  {
    label: 'System',
    keys: ['network', 'status', 'about'],
  },
  { label: 'Archived', keys: ['archive'] },
]

/**
 * Pages laid out as master–detail (a list rail beside an editor). They need the
 * width for both columns: at the shared 960px cap the editor column came out
 * around 590px, so its fields sat in one cramped stack with hundreds of unused
 * pixels beside them. Text-only preference pages stay narrow on purpose.
 */
const WIDE_SETTINGS_PAGES = new Set([
  'connections',
  'llm',
  'embedding',
  'search',
  'voice',
  'multimodal',
])

export function isWideSettingsPage(key: string): boolean {
  return WIDE_SETTINGS_PAGES.has(resolveSettingsKey(key))
}

/** Related service pages share a compact navigation row, with explicit tabs. */
export const SETTINGS_PAGE_FAMILIES: string[][] = [
  SETTINGS_CATEGORIES.find(category => category.key === 'agents')!.children!.map(leaf => leaf.key),
]

export function settingsPageFamily(key: string): string[] {
  return SETTINGS_PAGE_FAMILIES.find(family => family.includes(key)) ?? [key]
}

const extraPages: SettingsLeaf[] = [
  {
    key: 'progress',
    label: 'Learning progress',
    blurb: 'Reading progress and recent learning actions',
    icon: BarChart3,
    href: '/settings/progress',
    tile: '',
  },
  {
    key: 'data-migration',
    label: 'Data migration',
    blurb: 'Discover, migrate and export learning data',
    icon: Archive,
    href: '/settings/data-migration',
    tile: '',
  },
  {
    key: 'usage',
    label: 'Usage statistics',
    blurb: 'Model usage and conversation activity',
    icon: BarChart3,
    href: '/settings/usage',
    tile: '',
  },
  {
    key: 'archive',
    label: 'Archived chats',
    blurb: 'Search, unarchive, or permanently delete archived conversations',
    icon: Archive,
    href: '/settings/archive',
    tile: '',
  },
  {
    key: 'general',
    label: 'General',
    blurb: 'Interface language, layout, response language, and setup help',
    icon: Settings2,
    href: '/settings/general',
    tile: '',
  },
  {
    key: 'status',
    label: 'Runtime status',
    blurb: 'Service readiness, diagnostics, and memory usage',
    icon: Activity,
    href: '/settings/status',
    tile: '',
  },
]

export function visibleSettingsPages(access: SettingsAccess): SettingsLeaf[] {
  return [
    ...extraPages,
    ...SETTINGS_CATEGORIES.filter(category => isSettingsCategoryVisible(category, access))
      .flatMap(category => category.children ?? [{ ...category, tile: '' }])
      .filter(
        leaf => isSettingsLeafVisible(leaf, access) && resolveSettingsKey(leaf.key) === leaf.key
      ),
  ]
}

export function settingsPageLabel(key: string, fallback: string): string {
  if (key === 'llm') return 'Language models'
  if (key === 'agent-claude-code') return 'Partners & agents'
  if (key === 'starters') return 'Conversation'
  if (key === 'connections') return 'Providers'
  if (key === 'knowledge') return 'Knowledge & documents'
  return fallback
}

/**
 * Icon for a page as the navigation shows it.
 *
 * The counterpart to ``settingsPageLabel``: where a row stands for a whole
 * family it is titled for the family, so it cannot also wear one member's
 * brand mark. "Partners & agents" carried Claude Code's orange glyph — the one
 * saturated mark in a column of neutral line icons, and wrong about the page,
 * which configures every partner. Search results address the leaf itself and
 * keep the vendor glyph, matching the label they show.
 */
export function settingsPageIcon(key: string, fallback: LucideIcon): LucideIcon {
  if (key === 'agent-claude-code') return Bot
  return fallback
}

/** Old links sometimes placed ?profile after the fragment. Preserve it too. */
export function legacySettingsDestination(hash: string, search: string): string {
  const [rawKey, hashQuery = ''] = hash.replace(/^#/, '').split('?')
  let key = 'general'
  try {
    key = resolveSettingsKey(decodeURIComponent(rawKey || 'general'))
  } catch {
    /* malformed old URL */
  }
  const known = new Set([
    ...extraPages.map(page => page.key),
    ...SETTINGS_CATEGORIES.flatMap(
      category => category.children?.map(leaf => leaf.key) ?? [category.key]
    ),
  ])
  if (!known.has(key)) key = 'general'
  const query = new URLSearchParams(search)
  new URLSearchParams(hashQuery).forEach((value, name) => query.set(name, value))
  return `/settings/${key}${query.size ? `?${query}` : ''}`
}

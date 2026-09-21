import { Activity, Archive, BarChart3, Bot, Settings2 } from 'lucide-react'
import {
  SETTINGS_CATEGORIES,
  isSettingsCategoryVisible,
  isSettingsLeafVisible,
  resolveSettingsKey,
  type Lang,
  type SettingsLeaf,
} from './settings-nav'
import type { LucideIcon } from 'lucide-react'
import type { SettingsAccess } from './settings-access'

export const SETTINGS_PAGE_GROUPS: { label: Lang; keys: string[] }[] = [
  { label: { en: 'Personal', zh: '个人' }, keys: ['general', 'workspace', 'data-migration', 'appearance', 'usage'] },
  {
    label: { en: 'Learning & conversation', zh: '学习与对话' },
    keys: ['starters', 'attachments', 'video-learning', 'learner-profile', 'guardian', 'memory'],
  },
  {
    label: { en: 'Models & services', zh: '模型与服务' },
    keys: ['connections', 'llm', 'task-models', 'embedding', 'search', 'voice', 'multimodal'],
  },
  {
    label: { en: 'Features & integrations', zh: '功能与集成' },
    keys: ['tools', 'capabilities', 'agent-claude-code', 'knowledge'],
  },
  {
    label: { en: 'System', zh: '系统' },
    keys: ['network', 'status', 'about'],
  },
  { label: { en: 'Archived', zh: '已归档' }, keys: ['archive'] },
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
    key: 'data-migration',
    label: { en: 'Data migration', zh: '数据迁移' },
    blurb: { en: 'Discover, migrate and export learning data', zh: '查找、迁移和导出学习数据' },
    icon: Archive,
    href: '/settings/data-migration',
    tile: '',
  },
  {
    key: 'usage',
    label: { en: 'Usage statistics', zh: '用量统计' },
    blurb: { en: 'Model usage and conversation activity', zh: '模型用量与对话活跃情况' },
    icon: BarChart3,
    href: '/settings/usage',
    tile: '',
  },
  {
    key: 'archive',
    label: { en: 'Archived chats', zh: '已归档的聊天' },
    blurb: {
      en: 'Search, unarchive, or permanently delete archived conversations',
      zh: '搜索、取消归档或永久删除已归档的对话',
    },
    icon: Archive,
    href: '/settings/archive',
    tile: '',
  },
  {
    key: 'general',
    label: { en: 'General', zh: '常规' },
    blurb: {
      en: 'Interface language, response language, and setup help',
      zh: '界面语言、回复语言与配置帮助',
    },
    icon: Settings2,
    href: '/settings/general',
    tile: '',
  },
  {
    key: 'status',
    label: { en: 'Runtime status', zh: '运行状态' },
    blurb: {
      en: 'Service readiness, diagnostics, and memory usage',
      zh: '服务就绪情况、诊断与内存占用',
    },
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

export function settingsPageLabel(key: string, fallback: Lang): Lang {
  if (key === 'llm') return { en: 'Language models', zh: '语言模型' }
  if (key === 'agent-claude-code') return { en: 'Partners & agents', zh: '伙伴与智能体' }
  if (key === 'starters') return { en: 'Conversation', zh: '对话' }
  if (key === 'connections') return { en: 'Providers', zh: '提供方' }
  if (key === 'knowledge') return { en: 'Knowledge & documents', zh: '知识与文档' }
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

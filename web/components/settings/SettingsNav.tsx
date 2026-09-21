'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Search, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useSettingsAccess } from '@/features/settings/navigation/SettingsAccessProvider'
import { settingsAnchorHref, type Lang } from '@/features/settings/navigation/settings-nav'
import {
  SETTINGS_PAGE_GROUPS,
  settingsPageFamily,
  settingsPageIcon,
  settingsPageLabel,
  visibleSettingsPages,
} from '@/features/settings/navigation/settings-pages'

export default function SettingsNav({ onNavigate }: { onNavigate?: () => void }) {
  const { t, i18n } = useTranslation()
  const zh = i18n.language?.toLowerCase().startsWith('zh')
  const tr = (label: Lang) => (zh ? label.zh : label.en)
  const pathname = usePathname()
  const access = useSettingsAccess()
  const pages = visibleSettingsPages(access)
  const [query, setQuery] = useState('')
  const needle = query.trim().toLocaleLowerCase()
  const currentKey = pathname.split('/')[2] || 'general'
  const currentFamily = settingsPageFamily(currentKey)
  const matches = pages.filter(page =>
    [
      page.label.en,
      page.label.zh,
      page.blurb.en,
      page.blurb.zh,
      page.key,
      page.key === 'connections' ? 'API Key token base url 密钥 凭据 地址 供应商' : '',
      ...Object.values(settingsPageLabel(page.key, page.label)),
    ]
      .join(' ')
      .toLocaleLowerCase()
      .includes(needle)
  )
  const groups = needle
    ? [{ label: { en: 'Search results', zh: '搜索结果' }, pages: matches }]
    : SETTINGS_PAGE_GROUPS.map(group => ({
        ...group,
        pages: group.keys.flatMap(key => {
          // If the family representative is restricted, use its first visible member.
          const page = settingsPageFamily(key)
            .map(member => pages.find(item => item.key === member))
            .find(Boolean)
          return page ? [page] : []
        }),
      }))

  return (
    <nav aria-label={t('Settings sections')} className="flex min-h-0 flex-1 flex-col">
      <div className="relative mx-2.5 mb-2">
        <Search
          size={14}
          strokeWidth={1.8}
          className="pointer-events-none absolute left-2.5 top-[9px] text-[var(--muted-foreground)]"
        />
        <input
          aria-label={t('Search settings')}
          placeholder={t('Search settings')}
          value={query}
          onChange={event => setQuery(event.target.value)}
          className="w-full rounded-full bg-[var(--muted)] py-1.5 pl-8 pr-7 text-[13px] ring-1 ring-inset ring-transparent outline-none placeholder:text-muted-foreground/70 focus:ring-[var(--ring)]"
        />
        {query && (
          <button
            type="button"
            aria-label={t('Clear')}
            onClick={() => setQuery('')}
            className="absolute right-1.5 top-[7px] rounded p-0.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <X size={14} />
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-6">
        {groups
          .filter(group => group.pages.length)
          .map(group => (
            <div key={group.label.en} className="mb-0.5">
              <p className="px-2.5 pb-1 pt-3.5 text-[11px] font-medium text-muted-foreground">
                {tr(group.label)}
              </p>
              <div className="space-y-0.5">
                {group.pages.map(page => {
                  const Icon = needle ? page.icon : settingsPageIcon(page.key, page.icon)
                  const active = needle ? page.key === currentKey : currentFamily.includes(page.key)
                  return (
                    <Link
                      key={page.key}
                      href={settingsAnchorHref(page.key)}
                      scroll={false}
                      onClick={onNavigate}
                      aria-current={active ? 'page' : undefined}
                      title={tr(page.blurb)}
                      data-tour={`tour-nav-${page.key}`}
                      className={`flex min-h-8 items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${active ? 'bg-[var(--accent)] font-medium text-[var(--foreground)]' : 'text-[var(--foreground)] hover:bg-accent/60'}`}
                    >
                      <Icon size={15} strokeWidth={1.8} className="shrink-0" />
                      <span>
                        {tr(needle ? page.label : settingsPageLabel(page.key, page.label))}
                      </span>
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
        {needle && !matches.length && (
          <p className="px-2.5 py-5 text-[13px] text-[var(--muted-foreground)]">
            {t('No settings match “{{query}}”.', { query: query.trim() })}
          </p>
        )}
      </div>
    </nav>
  )
}

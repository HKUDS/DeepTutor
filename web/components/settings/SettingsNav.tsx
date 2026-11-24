'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Search, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import { useSettingsAccess } from '@/features/settings/navigation/SettingsAccessProvider'
import { settingsAnchorHref } from '@/features/settings/navigation/settings-nav'
import {
  SETTINGS_PAGE_GROUPS,
  settingsPageFamily,
  settingsPageIcon,
  settingsPageLabel,
  visibleSettingsPages,
} from '@/features/settings/navigation/settings-pages'

export default function SettingsNav({ onNavigate }: { onNavigate?: () => void }) {
  const { t, i18n } = useTranslation()
  // Fixed translators keep search bilingual (English + Chinese) regardless of
  // the active locale; rendering stays on t() with the active locale only.
  const tEn = i18n.getFixedT('en')
  const tZh = i18n.getFixedT('zh')
  const pathname = usePathname()
  const access = useSettingsAccess()
  const pages = visibleSettingsPages(access)
  const [query, setQuery] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const [moreBelow, setMoreBelow] = useState(false)
  const needle = query.trim().toLocaleLowerCase()
  const currentKey = pathname.split('/')[2] || 'general'
  const currentFamily = settingsPageFamily(currentKey)

  // The rail carries more sections than a 820px card can show (Search plus
  // five groups runs past the viewport), so the list scrolls. Without a cue the
  // last visible row is simply cut in half and reads as broken layout; the fade
  // only appears while there is actually more to scroll to, and disappears at
  // the end so the final row stays fully legible.
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const update = () =>
      setMoreBelow(el.scrollHeight - el.clientHeight - el.scrollTop > 8)
    update()
    el.addEventListener('scroll', update, { passive: true })
    const observer =
      typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update)
    observer?.observe(el)
    return () => {
      el.removeEventListener('scroll', update)
      observer?.disconnect()
    }
  }, [needle])
  const matches = pages.filter(page => {
    const navLabel = settingsPageLabel(page.key, page.label)
    return [
      page.label,
      t(page.label),
      tEn(page.label),
      tZh(page.label),
      page.blurb,
      t(page.blurb),
      tEn(page.blurb),
      tZh(page.blurb),
      navLabel,
      t(navLabel),
      tEn(navLabel),
      tZh(navLabel),
      page.key,
      page.key === 'connections' ? 'API Key token base url 密钥 凭据 地址 供应商' : '',
    ]
      .join(' ')
      .toLocaleLowerCase()
      .includes(needle)
  })
  const groups = needle
    ? [{ label: 'Search results', pages: matches }]
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
          className="pointer-events-none absolute left-2.5 top-3 text-[var(--muted-foreground)]"
        />
        <input
          aria-label={t('Search settings')}
          placeholder={t('Search settings')}
          value={query}
          onChange={event => setQuery(event.target.value)}
          className="w-full rounded-full bg-[var(--muted)] py-2.5 pl-8 pr-7 text-[13px] ring-1 ring-inset ring-transparent outline-none placeholder:text-muted-foreground/70 focus:ring-[var(--ring)]"
        />
        {query && (
          <button
            type="button"
            aria-label={t('Clear')}
            onClick={() => setQuery('')}
            className="absolute right-1.5 top-2.5 rounded p-0.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <X size={14} />
          </button>
        )}
      </div>
      <div className="relative min-h-0 flex-1">
        <div ref={listRef} className="h-full overflow-y-auto px-2.5 pb-6">
          {groups
            .filter(group => group.pages.length)
            .map(group => (
              <div key={group.label} className="mb-0.5">
                <p className="px-2.5 pb-1.5 pt-5 text-[12px] font-medium text-muted-foreground">
                  {t(group.label)}
                </p>
                <div className="space-y-0.5">
                  {group.pages.map(page => {
                    const Icon = needle ? page.icon : settingsPageIcon(page.key, page.icon)
                    const active = needle ? page.key === currentKey : currentFamily.includes(page.key)
                    return (
                      <Tooltip key={page.key} label={t(page.blurb)} as="div" side="right">
                        <Link
                          href={settingsAnchorHref(page.key)}
                          scroll={false}
                          onClick={onNavigate}
                          aria-current={active ? 'page' : undefined}
                          data-tour={`tour-nav-${page.key}`}
                          className={`flex min-h-9 items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${active ? 'bg-[var(--accent)] font-medium text-[var(--foreground)]' : 'text-[var(--foreground)] hover:bg-accent/60'}`}
                        >
                          <Icon size={15} strokeWidth={1.8} className="shrink-0" />
                          <span>
                            {t(needle ? page.label : settingsPageLabel(page.key, page.label))}
                          </span>
                        </Link>
                      </Tooltip>
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
        {moreBelow && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-[color-mix(in_srgb,var(--muted)_18%,var(--background))] to-transparent"
          />
        )}
      </div>
    </nav>
  )
}

'use client'
import { isNavigationTargetActive } from '@/lib/navigation'
import type { ReactNode } from 'react'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import type { LucideIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import { useSidebarDrawer } from '@/components/layout/AppShell'

export function NavigationRow({
  href,
  label,
  icon: Icon,
  detail,
  active,
  children,
  trailing,
}: {
  href: string
  label: string
  icon?: LucideIcon
  detail?: string
  active?: boolean
  children?: ReactNode
  trailing?: ReactNode
}) {
  const drawer = useSidebarDrawer()
  const pathname = usePathname()
  const search = useSearchParams()
  const selected =
    active ?? isNavigationTargetActive(href, pathname, new URLSearchParams(search.toString()))
  return (
    <Tooltip label={label} description={detail} as="div" side="right">
      <Link
        href={href}
        prefetch={false}
        onClick={event => {
          if (!event.metaKey && !event.ctrlKey && !event.shiftKey) drawer?.close()
        }}
        aria-current={selected ? 'page' : undefined}
        className={`dt-navigation-row ${selected ? 'is-active' : ''}`}
      >
        {children ?? (Icon && <Icon size={16} strokeWidth={1.6} />)}
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {trailing ??
          (detail && (
            <span className="max-w-[34%] truncate text-[11px] text-muted-foreground">{detail}</span>
          ))}
      </Link>
    </Tooltip>
  )
}
/**
 * A shelf's lead entry — the shelf's own home — set apart from the lists
 * beneath it, with room for one action on its right.
 */
export function OverviewRow({
  href,
  label,
  icon: Icon,
  action,
}: {
  href: string
  label: string
  icon: LucideIcon
  action?: ReactNode
}) {
  const drawer = useSidebarDrawer()
  const pathname = usePathname()
  const selected = pathname === href
  return (
    <div className={`dt-overview-row ${selected ? 'is-active' : ''}`}>
      <Link
        href={href}
        prefetch={false}
        aria-current={selected ? 'page' : undefined}
        onClick={event => {
          if (!event.metaKey && !event.ctrlKey && !event.shiftKey) drawer?.close()
        }}
      >
        <Icon size={16} strokeWidth={1.6} />
        <span>{label}</span>
      </Link>
      {action}
    </div>
  )
}
export function Section({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="dt-navigation-section">
      <div className="dt-navigation-heading">
        <span>{title}</span>
        {action}
      </div>
      {children}
    </section>
  )
}
export function Status({
  loading,
  error,
  retry,
}: {
  loading: boolean
  error: boolean
  retry: () => void
}) {
  const { t } = useTranslation()
  if (loading)
    return (
      <div aria-busy="true" className="space-y-3 px-3 py-4">
        {[0, 1, 2].map(value => (
          <div key={value} className="h-3 w-4/5 animate-pulse rounded bg-muted" />
        ))}
      </div>
    )
  return error ? (
    <div className="px-3 py-2 text-xs text-muted-foreground" role="status">
      {t('navigation.loadError')}{' '}
      <button className="underline" onClick={retry}>
        {t('Retry')}
      </button>
    </div>
  ) : null
}
export const matches = (label: string, query: string) =>
  label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())

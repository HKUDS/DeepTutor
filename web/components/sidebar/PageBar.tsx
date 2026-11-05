'use client'

import { usePathname } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { useAuthStatus } from '@/hooks/useAuthStatus'
import { useDevice } from '@/hooks/useDevice'
import { useCapabilityFilter } from '@/features/capabilities/useCapabilityCatalog'
import { usePageSlotRef } from '@/components/layout/PageChrome'
import { FeatureCrumb } from '@/components/layout/LocationCrumbs'
import { locatePage, pageSections } from './page-sections'

function useShelves() {
  const { t, i18n } = useTranslation()
  const { learningPolicy } = useAuthStatus()
  const isAvailable = useCapabilityFilter()
  return pageSections({
    t,
    zh: (i18n?.language ?? '').startsWith('zh'),
    allowedSurfaces: learningPolicy?.allowedSurfaces ?? null,
    isAvailable,
  })
}

/**
 * The shelf and feature entry for a feature page, for views that draw the
 * crumbs in a toolbar of their own (see `OWN_HEADER`).
 */
export function useShelfFeature(href: string) {
  const sections = useShelves()
  for (const section of sections) {
    const page = section.pages.find(entry => entry.href === href)
    if (page) return { section, page }
  }
  return null
}

/**
 * The top of every page: 「feature / the one use of it that is open」 on the
 * left and the page's own actions on the right. The feature opens onto the
 * other features of its sidebar shelf; the page hands up the rest — its
 * instance crumb (see `InstanceCrumb`), its meta and actions — through
 * `PageBarSlot`. Rendered by the route layouts above the page, so pages
 * need no wiring and their own "back to section" links become redundant
 * (modern.css hides them). Which workspace this is shows only in the
 * sidebar: every page here belongs to the current one.
 */
export function PageBar() {
  const { t } = useTranslation()
  const pathname = usePathname() ?? ''
  const { isMobile } = useDevice()
  const instanceRef = usePageSlotRef('instance')
  const metaRef = usePageSlotRef('meta')
  const actionsRef = usePageSlotRef('actions')
  const located = locatePage(pathname, useShelves())
  // Phones have their own top row; without the bar, headers keep everything.
  if (!located || isMobile) return null
  // On the feature page itself the bar is the header; under a detail page
  // it locates it, and the page keeps its own title and meta.
  const exact = located.page.href === pathname
  return (
    <nav aria-label={t('navigation.location')} className="dt-page-bar" data-exact={exact || undefined}>
      <FeatureCrumb section={located.section} page={located.page} />
      <div ref={instanceRef} className="dt-page-bar-instance" />
      {exact && <div ref={metaRef} className="dt-page-bar-meta" />}
      <div ref={actionsRef} className="dt-page-bar-actions" />
    </nav>
  )
}

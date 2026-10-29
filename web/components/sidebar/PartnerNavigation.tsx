'use client'
import { useTranslation } from 'react-i18next'
import { NavigationRow, Status, matches } from './NavigationPrimitives'
import { PartnerRoster } from './PartnerRoster'
import { RecordGroups, RecordHeader, RecordTime, useRecordView } from './RecordList'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { Plus, ChevronRight, MessageCircle, Users } from 'lucide-react'
import PartnerAvatar from '@/components/partners/PartnerAvatar'
import { usePartnerNavigation } from '@/hooks/usePartnerNavigation'
import { partnerSessionHref } from '@/lib/navigation'

export function PartnerNavigation({ active = true }: { active?: boolean }) {
  const { t } = useTranslation()
  const search = useSearchParams()
  const pathname = usePathname()
  const { data, loading, error, retry } = usePartnerNavigation(active)
  const view = useRecordView('deeptutor.navigation.partners.sort')
  const { partners, groups, sessions } = data
  const partnersById = new Map(partners.map(partner => [partner.partner_id, partner]))
  const sessionRows = sessions.filter(row =>
    matches(`${row.title} ${row.owner_name}`, view.query)
  )
  return (
    <div className="dt-partner-navigation">
      <section className="dt-partner-preview" aria-labelledby="partner-preview-title">
        <div className="dt-navigation-heading">
          <h2 id="partner-preview-title">
            {t('navigation.partners')}{' '}
            <span className="dt-navigation-count">{partners.length}</span>
          </h2>
          <div className="dt-navigation-actions">
            <Link
              prefetch={false}
              href="/partners#partners"
              aria-label={t('navigation.allPartners')}
              className="dt-navigation-view-all"
            >
              {t('navigation.viewAll')}
              <ChevronRight size={12} />
            </Link>
            <Link
              prefetch={false}
              href="/partners/new"
              aria-label={t('New partner')}
              className="dt-nav-icon"
            >
              <Plus size={15} strokeWidth={1.7} />
            </Link>
          </div>
        </div>
        <PartnerRoster partners={partners} activeHref={pathname} />
        {!loading && !partners.length && (
          <p className="dt-navigation-empty">
            {t('No partners yet')}
          </p>
        )}
      </section>
      <section className="dt-partner-preview" aria-labelledby="group-preview-title">
        <div className="dt-navigation-heading">
          <h2 id="group-preview-title">
            {t('Groups')} <span className="dt-navigation-count">{groups.length}</span>
          </h2>
          <div className="dt-navigation-actions">
            <Link
              prefetch={false}
              href="/partners#groups"
              aria-label={t('navigation.allGroups')}
              className="dt-navigation-view-all"
            >
              {t('navigation.viewAll')}
              <ChevronRight size={12} />
            </Link>
            {data.partners.length >= 2 && (
              <Link
                prefetch={false}
                className="dt-nav-icon"
                href="/partners/groups/new"
                aria-label={t('New group')}
              >
                <Plus size={15} strokeWidth={1.7} />
              </Link>
            )}
          </div>
        </div>
        {groups.slice(0, 2).map(group => (
          <NavigationRow
            key={group.group_id}
            href={`/partners/groups/${encodeURIComponent(group.group_id)}`}
            label={group.name}
            icon={Users}
          />
        ))}
        {!loading && !groups.length && (
          <p className="dt-navigation-empty">
            {t('navigation.noGroups')}
          </p>
        )}
      </section>
      <section className="dt-partner-sessions" aria-label={t('navigation.partnerSessions')}>
        <RecordHeader
          title={t('navigation.partnerSessions')}
          count={sessionRows.length}
          view={view}
          searchLabel={t('navigation.searchPartnerSessions')}
          // Partner transcripts record their last activity only.
          sorts={['updatedAt']}
        />
        <div
          className="dt-partner-session-list"
          tabIndex={0}
          role="region"
          aria-label={t('navigation.partnerSessions')}
        >
          <Status loading={loading} error={error || data.unavailable.length > 0} retry={retry} />
          <RecordGroups
            rows={sessionRows}
            view={view}
            time={row => row.updated_at}
            renderRow={row => {
              const href = partnerSessionHref(row)
              const partner = row.kind === 'partner' ? partnersById.get(row.owner_id) : undefined
              return (
                <NavigationRow
                  key={`${row.kind}:${row.owner_id}:${row.session_key}`}
                  href={href}
                  label={row.title || t('New conversation')}
                  detail={row.owner_name}
                  icon={row.kind === 'group' ? Users : MessageCircle}
                  active={
                    pathname === href.split('?')[0] && search.get('session') === row.session_key
                  }
                  trailing={<RecordTime seconds={row.updated_at} />}
                >
                  {partner ? (
                    <PartnerAvatar
                      name={partner.name}
                      emoji={partner.emoji}
                      image={partner.avatar}
                      color={partner.color}
                      size={16}
                    />
                  ) : undefined}
                </NavigationRow>
              )
            }}
            empty={
              !loading &&
              !error && (
                <p className="dt-navigation-empty">
                  {t(view.query ? 'navigation.noResults' : 'navigation.noSessions')}
                </p>
              )
            }
          />
        </div>
      </section>
    </div>
  )
}

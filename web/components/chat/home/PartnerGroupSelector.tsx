'use client'

import Link from 'next/link'
import { Check, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { PartnerGroup } from '@/lib/partner-groups-api'

export default function PartnerGroupSelector({
  groups,
  selected,
  onSelect,
  error,
  loading,
}: {
  groups: PartnerGroup[]
  selected: string | null
  onSelect: (id: string | null) => void
  error: boolean
  loading: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="min-w-[240px] p-2">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm hover:bg-[var(--muted)]"
      >
        {t('None')}
        {!selected && <Check size={14} />}
      </button>
      {loading && (
        <p className="px-3 py-2 text-sm text-[var(--muted-foreground)]">{t('Loading...')}</p>
      )}
      {error && (
        <p role="alert" className="px-3 py-2 text-sm text-[var(--muted-foreground)]">
          {t('Could not load partner groups')}
        </p>
      )}
      {!loading && !error && !groups.length && (
        <p className="px-3 py-2 text-sm text-[var(--muted-foreground)]">
          {t('No partner groups yet')}
        </p>
      )}
      <div className="max-h-64 overflow-y-auto">
        {groups.map(group => (
          <button
            type="button"
            key={group.group_id}
            onClick={() => onSelect(group.group_id)}
            aria-pressed={selected === group.group_id}
            className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--muted)]"
          >
            <span>
              {group.emoji || '👥'} {group.name}
              <span className="block text-xs text-[var(--muted-foreground)]">
                {group.members.map(member => member.name).join(' · ')}
              </span>
            </span>
            {selected === group.group_id && <Check size={14} />}
          </button>
        ))}
      </div>
      <Link
        href="/partners/groups/new"
        className="mt-2 flex items-center gap-2 border-t border-[var(--border)] px-3 py-3 text-sm"
      >
        <Plus size={15} />
        {t('Create partner group')}
      </Link>
    </div>
  )
}

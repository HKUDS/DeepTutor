'use client'

import Link from 'next/link'
import { Check, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import PartnerAvatar from '@/components/partners/PartnerAvatar'
import type { PartnerInfo } from '@/lib/partners-api'

export default function PartnerSelector({
  partners,
  selected,
  onSelect,
  loading,
  error,
}: {
  partners: PartnerInfo[]
  selected: string | null
  onSelect: (id: string | null) => void
  loading: boolean
  error: boolean
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
        <p role="alert" className="px-3 py-2 text-sm">
          {t('Could not load partners')}
        </p>
      )}
      {!loading && !error && !partners.length && (
        <p className="px-3 py-2 text-sm text-[var(--muted-foreground)]">{t('No partners yet')}</p>
      )}
      <div className="max-h-64 overflow-y-auto">
        {partners.map(partner => (
          <button
            type="button"
            key={partner.partner_id}
            onClick={() => onSelect(partner.partner_id)}
            aria-pressed={selected === partner.partner_id}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--muted)]"
          >
            <PartnerAvatar
              name={partner.name}
              emoji={partner.emoji}
              color={partner.color}
              image={partner.avatar}
              size={28}
            />
            <span className="min-w-0 flex-1 truncate">{partner.name}</span>
            {selected === partner.partner_id && <Check size={14} />}
          </button>
        ))}
      </div>
      <Link
        href="/partners"
        className="mt-2 flex items-center gap-2 border-t border-[var(--border)] px-3 py-3 text-sm"
      >
        <Plus size={15} />
        {t('Partners')}
      </Link>
    </div>
  )
}

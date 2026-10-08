'use client'

import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ProviderIcon from '@/components/common/ProviderIcon'
import { formatProviderLabel } from '@/lib/provider-branding'
import type { ApiFormat, ServiceName } from '@/lib/model-catalog-types'
import { SERVICE_TITLES } from '@/lib/provider-registry'
import { inputClass, selectClass, subPanelClass } from './shared'
import { registryButton, registryPrimary } from './RegistryControls'

export type ProviderCatalogOption = { value: string; label: string; services: ServiceName[] }
export type CustomProviderInput = { name: string; base_url: string; api_format: ApiFormat }
const FILTERS = [
  'all',
  'multi',
  'llm',
  'embedding',
  'voice',
  'search',
  'imagegen',
  'videogen',
  'custom',
] as const
const PROTOCOLS = {
  openai_chat: 'OpenAI Chat Completions',
  openai_responses: 'OpenAI Responses',
  anthropic: 'Anthropic Messages',
} as const
export function ProviderProtocol({
  value,
  onChange,
  allowAuto = true,
  formats,
}: {
  value: ApiFormat
  onChange: (value: ApiFormat) => void
  allowAuto?: boolean
  formats?: readonly string[]
}) {
  const { t } = useTranslation()
  return (
    <label className="block space-y-1.5 text-[13px] font-medium">
      <span>{t('settings.providerServices.protocol')}</span>
      <select
        className={selectClass}
        value={value}
        onChange={e => onChange(e.target.value as ApiFormat)}
      >
        {allowAuto && (!formats || formats.includes('auto')) && <option value="auto">{t('Auto')}</option>}
        {Object.entries(PROTOCOLS).filter(([key]) => !formats || formats.includes(key)).map(([key, label]) => (
          <option key={key} value={key}>
            {t(label)}
          </option>
        ))}
      </select>
    </label>
  )
}
export function AddProviderPanel({
  options,
  vendor,
  onVendor,
  onCreate,
  onCancel,
}: {
  options: ProviderCatalogOption[]
  vendor: string
  onVendor: (value: string) => void
  onCreate: (custom?: CustomProviderInput) => void
  onCancel: () => void
}) {
  const { t, i18n } = useTranslation()
  const uiLanguage = i18n?.resolvedLanguage ?? i18n?.language ?? 'en'
  const radioName = useId()
  const [filter, setFilter] = useState<string>('all')
  const [query, setQuery] = useState('')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [protocol, setProtocol] = useState<ApiFormat>('openai_chat')
  const custom = vendor === 'custom'
  const visible = options.map(option => ({
    ...option,
    label: formatProviderLabel(option.value, option.label, uiLanguage),
  })).filter(option => {
    const category =
      filter === 'all' ||
      (filter === 'custom'
        ? option.value === 'custom'
        : option.value !== 'custom' &&
          (filter === 'multi'
            ? option.services.length > 1
            : filter === 'voice'
              ? option.services.some(s => s === 'tts' || s === 'stt')
              : option.services.includes(filter as ServiceName)))
    return (
      category &&
      `${option.label} ${option.value}`.toLowerCase().includes(query.trim().toLowerCase())
    )
  })
  let validUrl = false
  try {
    const parsed = new URL(url)
    validUrl =
      ['https:', 'http:'].includes(parsed.protocol) &&
      !parsed.username &&
      !parsed.password &&
      Boolean(parsed.hostname)
  } catch {}
  return (
    <section aria-label={t('Add provider')} className={`min-w-0 space-y-5 p-4 sm:p-6 ${subPanelClass}`}>
      <h3 className="text-base font-semibold">{t('Add provider')}</h3>
      <input
        type="search"
        className={inputClass}
        value={query}
        aria-label={t('settings.providerServices.search')}
        placeholder={t('settings.providerServices.search')}
        onChange={e => setQuery(e.target.value)}
      />
      <div
        role="group"
        aria-label={t('settings.providerServices.filter')}
        className="flex flex-wrap gap-1.5"
      >
        {FILTERS.map(item => (
          <button
            type="button"
            key={item}
            aria-pressed={filter === item}
            onClick={() => {
              setFilter(item)
              onVendor('')
            }}
            className={`rounded-full border px-3 py-1.5 text-[13px] ${filter === item ? 'border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]' : 'border-[var(--border)] hover:bg-[var(--accent)]'}`}
          >
            {t(`settings.providerServices.filter.${item}`)}
          </button>
        ))}
      </div>
      <div
        role="radiogroup"
        aria-label={t('Provider type')}
        className="grid max-h-[min(28rem,50dvh)] grid-cols-[repeat(auto-fill,minmax(min(100%,22rem),1fr))] gap-3 overflow-y-auto overscroll-contain p-1"
      >
        {visible.map(option => (
          <label
            key={option.value}
            className={`relative flex min-h-24 min-w-0 flex-col rounded-xl border p-4 text-left cursor-pointer outline-none has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--ring)] ${vendor === option.value ? 'border-[var(--primary)] bg-[var(--accent)]' : 'border-[var(--border)] bg-[var(--background)] hover:bg-[var(--accent)]'}`}
          >
            {/* Anchor the hidden radio to its card so focus cannot scroll the settings shell. */}
            <input type="radio" className="sr-only" name={radioName} value={option.value} aria-label={option.value === 'custom' ? t('Custom') : option.label} checked={vendor === option.value} onChange={() => onVendor(option.value)} />
            <span className="flex items-start gap-2.5 text-[15px] font-medium leading-6">
              <ProviderIcon provider={option.value} size={20} />
              <span className="min-w-0 break-words">{option.value === 'custom' ? t('Custom') : option.label}</span>
            </span>
            <span className="mt-3 flex flex-wrap gap-1.5">
              {option.value === 'custom' ? (
                <span className="text-[13px] text-[var(--muted-foreground)]">
                  {t('settings.providerServices.customHint')}
                </span>
              ) : (
                option.services.map(service => (
                  <span
                    key={service}
                    className="rounded bg-[var(--muted)] px-2 py-0.5 text-[12px] text-[var(--muted-foreground)]"
                  >
                    {t(SERVICE_TITLES[service])}
                  </span>
                ))
              )}
            </span>
          </label>
        ))}
      </div>
      {!visible.length && (
        <p role="status" className="py-3 text-[13px] text-[var(--muted-foreground)]">
          {t('settings.providerServices.noMatch')}
        </p>
      )}
      {custom && (
        <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
          <label className="block space-y-1.5 text-[13px] font-medium">
            <span>{t('settings.providerServices.name')}</span>
            <input className={inputClass} value={name} onChange={e => setName(e.target.value)} />
          </label>
          <label className="block space-y-1.5 text-[13px] font-medium">
            <span>{t('Provider URL')}</span>
            <input className={inputClass} value={url} onChange={e => setUrl(e.target.value)} />
          </label>
          {url && !validUrl && (
            <p role="status" className="text-[13px] text-red-600">
              {t('Enter a valid HTTP or HTTPS provider address.')}
            </p>
          )}
          <ProviderProtocol value={protocol} onChange={setProtocol} allowAuto={false} />
          <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
            {t('settings.providerServices.customDescription')}
          </p>
        </div>
      )}
      <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
        {t('settings.providerServices.addHint')}
      </p>
      <div className="flex gap-2 border-t border-[var(--border)] pt-4">
        <button
          type="button"
          className={registryPrimary}
          disabled={
            !vendor ||
            !visible.some(p => p.value === vendor) ||
            (custom && (!name.trim() || !validUrl))
          }
          onClick={() =>
            onCreate(
              custom ? { name: name.trim(), base_url: url.trim(), api_format: protocol } : undefined
            )
          }
        >
          {t('Continue')}
        </button>
        <button type="button" className={registryButton} onClick={onCancel}>
          {t('Cancel')}
        </button>
      </div>
    </section>
  )
}

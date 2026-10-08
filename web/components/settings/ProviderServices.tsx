'use client'

import { useTranslation } from 'react-i18next'
import { useSettings, type ServiceName } from '@/features/settings/store/SettingsStore'
import type { ProviderServiceOverrides } from '@/lib/model-catalog-types'
import { formatProviderLabel } from '@/lib/provider-branding'
import {
  PROVIDER_SERVICES,
  SERVICE_TITLES,
  providerAdapter,
  providerServiceSupport,
  type ProviderSource,
} from '@/lib/provider-registry'
import { inputClass, selectClass } from './shared'

export function ProviderServices({
  source,
  onChange,
}: {
  source: ProviderSource
  onChange: (value: ProviderServiceOverrides) => void
}) {
  const { t, i18n } = useTranslation()
  const uiLanguage = i18n?.resolvedLanguage ?? i18n?.language ?? 'en'
  const { providers, connectionTargets } = useSettings()
  const overrides = source.source.service_overrides ?? {}
  function patch(service: ServiceName, value: object) {
    onChange({ ...overrides, [service]: { ...overrides[service], ...value } })
  }
  return (
    <section
      aria-label={t('settings.providerServices.title')}
      className="space-y-3 border-t border-[var(--border)] pt-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium">{t('settings.providerServices.title')}</h4>
        {Object.keys(overrides).length > 0 && (
          <button
            type="button"
            className="text-[13px] underline underline-offset-4"
            onClick={() => onChange({})}
          >
            {t('settings.providerServices.reset')}
          </button>
        )}
      </div>
      <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
        {t('settings.providerServices.description')}
      </p>
      <div className="grid gap-2.5 sm:grid-cols-2">
        {PROVIDER_SERVICES.map(service => {
          const support = providerServiceSupport(source, service, connectionTargets, providers)
          const adapter = providerAdapter(source, service, connectionTargets, providers)
          const options = (providers[service] ?? []).filter(
            p => p.value !== 'none' && p.status !== 'deprecated'
          )
          const defaultBinding = options.some(p => p.value === adapter.binding)
            ? adapter.binding
            : service === 'search'
              ? options[0]?.value
              : 'custom'
          const binding = overrides[service]?.binding || defaultBinding || ''
          return (
            <div
              key={service}
              className={`min-w-0 rounded-xl border p-3.5 transition-colors ${support.enabled ? "border-[color-mix(in_srgb,var(--primary)_22%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_3%,var(--background))]" : "border-[color-mix(in_srgb,var(--border)_70%,transparent)]"}`}
            >
              <label className="flex cursor-pointer items-start gap-3 text-[13px] leading-5">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
                  checked={support.enabled}
                  onChange={e =>
                    patch(service, {
                      enabled: e.target.checked,
                      ...(e.target.checked ? { binding } : {}),
                    })
                  }
                />
                <span>
                  <span className="block font-medium">{t(SERVICE_TITLES[service])}</span>
                  <span className="mt-1 block text-[12px] text-[var(--muted-foreground)]">
                    {t(`settings.providerServices.evidence.${support.evidence}`)}
                  </span>
                </span>
              </label>
              {support.enabled && service !== 'llm' && (
                <details className="mt-3 border-t border-[color-mix(in_srgb,var(--border)_65%,transparent)] pt-3 text-[13px]">
                  <summary className="cursor-pointer text-[var(--muted-foreground)]">
                    {t('settings.providerServices.connection')}
                  </summary>
                  <div className="mt-3 space-y-3">
                    <label className="block space-y-1.5">
                      <span>{t('settings.providerServices.adapter')}</span>
                      <select
                        className={selectClass}
                        value={binding}
                        onChange={e => patch(service, { enabled: true, binding: e.target.value })}
                      >
                        {!options.some(p => p.value === binding) && (
                          <option value={binding}>{binding || t('Choose a provider')}</option>
                        )}
                        {options.map(option => (
                          <option key={option.value} value={option.value}>
                            {formatProviderLabel(option.value, option.label, uiLanguage)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block space-y-1.5">
                      <span>{t('settings.providerServices.url')}</span>
                      <input
                        className={inputClass}
                        value={overrides[service]?.base_url ?? ''}
                        placeholder={t('settings.providerServices.inheritUrl')}
                        onChange={e =>
                          patch(service, { enabled: true, binding, base_url: e.target.value })
                        }
                      />
                    </label>
                    {service === 'search' && (
                      <p className="leading-relaxed text-[var(--muted-foreground)]">
                        {t('settings.providerServices.searchProtocol')}
                      </p>
                    )}
                    {service === 'videogen' && (
                      <p className="leading-relaxed text-[var(--muted-foreground)]">
                        {t('settings.serviceConfig.video')}
                      </p>
                    )}
                  </div>
                </details>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

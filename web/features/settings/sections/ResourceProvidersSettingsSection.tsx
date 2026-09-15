'use client'

import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Toggle } from '@/components/settings/Toggle'
import { SettingRow, SettingSection, SettingsPageHeader } from '@/components/settings/shared'
import { apiFetch, apiUrl } from '@/lib/api'

type ResourceProvider = {
  name: string
  type: string
  version: string
  languages: string[]
  offline: boolean
  permissions: string[]
  description: string
  enabled: boolean
}

function isResourceProvider(value: unknown): value is ResourceProvider {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return (
    typeof row.name === 'string' &&
    typeof row.type === 'string' &&
    typeof row.version === 'string' &&
    Array.isArray(row.languages) &&
    row.languages.every(language => typeof language === 'string') &&
    typeof row.offline === 'boolean' &&
    Array.isArray(row.permissions) &&
    row.permissions.every(permission => typeof permission === 'string') &&
    typeof row.description === 'string' &&
    typeof row.enabled === 'boolean'
  )
}

export default function ResourceProvidersSettingsPage() {
  const { t } = useTranslation()
  const [providers, setProviders] = useState<ResourceProvider[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [pending, setPending] = useState<Set<string>>(() => new Set())

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const response = await apiFetch(apiUrl('/api/capabilities/resource-providers'))
      const payload = (await response.json().catch(() => null)) as
        { providers?: unknown } | { detail?: unknown } | null
      if (!response.ok) {
        const detail =
          payload && 'detail' in payload && typeof payload.detail === 'string'
            ? payload.detail
            : undefined
        throw new Error(detail ?? `HTTP ${response.status}`)
      }
      const rows = payload && 'providers' in payload ? payload.providers : null
      if (!Array.isArray(rows) || !rows.every(isResourceProvider)) {
        throw new Error(t('Unexpected resource provider response.'))
      }
      setProviders(rows)
    } catch (err) {
      setProviders(null)
      setLoadError(err instanceof Error ? err.message : String(err))
    }
  }, [t])

  useEffect(() => {
    void load()
  }, [load])

  const handleToggle = useCallback(
    async (name: string, enabled: boolean) => {
      if (pending.has(name)) return
      const snapshot = providers
      if (!snapshot) return

      const next = snapshot.map(provider =>
        provider.name === name ? { ...provider, enabled } : provider
      )
      setProviders(next)
      setPending(current => new Set(current).add(name))
      setSaveError(null)

      try {
        const response = await apiFetch(
          apiUrl(`/api/capabilities/resource-providers/${encodeURIComponent(name)}/state`),
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
          }
        )
        const row = await response.json().catch(() => null)
        if (!response.ok) {
          const detail =
            row && typeof row === 'object' && 'detail' in row
              ? (row as { detail?: unknown }).detail
              : undefined
          throw new Error(typeof detail === 'string' ? detail : `HTTP ${response.status}`)
        }
        if (!isResourceProvider(row)) {
          throw new Error(t('Unexpected resource provider response.'))
        }
        setProviders(
          current => current?.map(provider => (provider.name === name ? row : provider)) ?? current
        )
      } catch (err) {
        setProviders(snapshot)
        setSaveError(err instanceof Error ? err.message : String(err))
      } finally {
        setPending(current => {
          const remaining = new Set(current)
          remaining.delete(name)
          return remaining
        })
      }
    },
    [pending, providers, t]
  )

  return (
    <div>
      <SettingsPageHeader
        title={t('Resource Providers')}
        description={t(
          'Control which learning-resource providers answer bounded lookups. Disabled providers stay registered and keep their configuration.'
        )}
      />

      {loadError && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {t('Failed to load resource providers.')} {loadError}
        </div>
      )}

      {saveError && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {t('Failed to save resource provider state.')} {saveError}
        </div>
      )}

      {!providers && !loadError && (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('Loading resource providers...')}
        </div>
      )}

      {providers && (
        <SettingSection
          title={t('Installed providers')}
          description={t(
            'Changes take effect for new lookups immediately and persist across restarts.'
          )}
        >
          {providers.length === 0 ? (
            <p className="py-4 text-[13px] text-[var(--muted-foreground)]">
              {t('No resource providers are registered.')}
            </p>
          ) : (
            providers.map(provider => {
              const metadata = [
                provider.type,
                `v${provider.version}`,
                provider.languages.map(language => language.toUpperCase()).join(' / '),
              ].join(' · ')

              return (
                <SettingRow
                  key={provider.name}
                  title={provider.name}
                  description={provider.description || metadata}
                  control={
                    <div className="flex items-center gap-3">
                      <div className="text-right">
                        <div className="font-mono text-[11px] text-[var(--muted-foreground)]">
                          {metadata}
                        </div>
                        <div className="mt-1 flex items-center justify-end gap-2">
                          <span className="inline-flex items-center rounded-full border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                            {provider.offline ? t('Offline') : t('Online')}
                          </span>
                          <span className="text-[11px] text-[var(--muted-foreground)]">
                            {provider.enabled ? t('Enabled') : t('Disabled')}
                          </span>
                        </div>
                      </div>
                      <Toggle
                        checked={provider.enabled}
                        disabled={pending.size > 0}
                        onChange={next => void handleToggle(provider.name, next)}
                        label={t('Toggle {{name}}', { name: provider.name })}
                      />
                    </div>
                  }
                />
              )
            })
          )}
        </SettingSection>
      )}
    </div>
  )
}

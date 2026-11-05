'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useSettings, type CatalogProfile } from '@/features/settings/store/SettingsStore'
import { apiFetch, apiUrl } from '@/lib/api'
import {
  flattenModels,
  modelProviderRef,
  providerIdentity,
  providerRegistry,
  stageRegistryAction,
  type ProviderSource,
} from '@/lib/provider-registry'
import { randomUuid } from '@/lib/random-uuid'
import { registryButton, registryPrimary } from './RegistryControls'
import { selectClass, subPanelClass } from './shared'

/** Discover CLI-owned models and stage choices in the shared settings draft. */
export function AntigravityModelsCard({ source }: { source: ProviderSource }) {
  const { t } = useTranslation()
  const { draft, catalog, mutateCatalog, applying } = useSettings()
  const pickerId = useId()
  const controller = useRef<AbortController | null>(null)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  const [selected, setSelected] = useState('')
  useEffect(() => () => controller.current?.abort(), [])

  const rows = flattenModels(draft, ['llm']).filter(
    row =>
      row.model?.model &&
      providerIdentity(modelProviderRef('llm', row.profile, row.model)) === source.id
  )
  const active = draft.services.llm
  const picked =
    rows.find(row => row.key === selected) ??
    rows.find(
      row => row.profile.id === active.active_profile_id && row.model?.id === active.active_model_id
    ) ??
    rows[0]
  const isDefault = Boolean(
    picked &&
    active.active_profile_id === picked.profile.id &&
    active.active_model_id === picked.model?.id
  )
  const isLiveDefault =
    isDefault &&
    catalog.services.llm.active_profile_id === picked?.profile.id &&
    catalog.services.llm.active_model_id === picked?.model?.id

  const refresh = async () => {
    controller.current?.abort()
    const request = new AbortController()
    controller.current = request
    setPending(true)
    setMessage('')
    const timer = setTimeout(() => request.abort(), 35_000)
    try {
      const response = await apiFetch(apiUrl('/api/settings/fetch-models'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ binding: 'antigravity', service: 'llm', base_url: '' }),
        signal: request.signal,
      })
      if (!response.ok) throw new Error('discovery_failed')
      const payload = await response.json()
      if (request.signal.aborted) return
      const ids = [
        ...new Set<string>(
          (payload.models ?? [])
            .map((model: { id?: unknown }) => model.id)
            .filter((id: unknown): id is string => typeof id === 'string' && Boolean(id.trim()))
        ),
      ]
      if (!ids.length) throw new Error('empty_models')
      mutateCatalog(next => {
        // Resolve against the current draft, not the snapshot that started I/O.
        const current = providerRegistry(next).find(item => item.id === source.id)
        if (!current || current.provider !== 'antigravity') return
        current.source.discovery = {
          status: 'connected',
          models: ids.map(id => ({ id })),
          checked_at: new Date().toISOString(),
        }
        const existing = flattenModels(next, ['llm']).filter(
          row => providerIdentity(modelProviderRef('llm', row.profile, row.model)) === source.id
        )
        const missing = ids.filter(id => !existing.some(row => row.model?.model === id))
        if (!missing.length) return
        let profile: CatalogProfile | undefined = existing[0]?.profile
        if (!profile && source.ref.service === 'llm') {
          profile = next.services.llm.profiles.find(item => item.id === source.ref.profile_id)
        }
        if (!profile) {
          profile = {
            id: `llm-profile-${randomUuid()}`,
            name: current.name,
            binding: 'antigravity',
            provider_ref: { ...current.ref, binding: 'antigravity' },
            api_key: '',
            base_url: '',
            api_version: '',
            models: [],
          }
          next.services.llm.profiles.push(profile)
        }
        profile.provider_only = false
        profile.models.push(
          ...missing.map(model => ({
            id: `llm-model-${randomUuid()}`,
            name: model,
            model,
            provider_ref: { ...current.ref, binding: 'antigravity' },
          }))
        )
      })
      setMessage(t('antigravity.models.refreshed', { count: ids.length }))
    } catch {
      if (controller.current === request) setMessage(t('antigravity.models.failed'))
    } finally {
      clearTimeout(timer)
      if (controller.current === request) setPending(false)
    }
  }

  return (
    <section
      className={`space-y-3 p-4 ${subPanelClass}`}
      aria-label={t('antigravity.models.title')}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm font-medium">{t('antigravity.models.title')}</p>
        <button
          type="button"
          className={registryButton}
          disabled={pending || applying}
          onClick={() => void refresh()}
        >
          <RefreshCw size={14} className={pending ? 'animate-spin' : ''} />
          {t(pending ? 'antigravity.models.refreshing' : 'antigravity.models.refresh')}
        </button>
      </div>
      <p className="text-[13px] text-[var(--muted-foreground)]">
        {t('antigravity.auth.description')}
      </p>
      {rows.length ? (
        <>
          <label htmlFor={pickerId} className="block text-sm">
            {t('antigravity.models.choose')}
          </label>
          <select
            id={pickerId}
            className={selectClass}
            value={picked?.key ?? ''}
            disabled={applying}
            onChange={event => setSelected(event.target.value)}
          >
            {rows.map(row => (
              <option key={row.key} value={row.key}>
                {row.model?.name || row.model?.model}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={registryPrimary}
            disabled={applying || isDefault || !picked}
            onClick={() => {
              if (!picked) return
              mutateCatalog(next =>
                stageRegistryAction(next, {
                  kind: 'default',
                  service: 'llm',
                  profile_id: picked.profile.id,
                  model_id: picked.model?.id,
                })
              )
            }}
          >
            {t('antigravity.models.useDefault')}
          </button>
          {isDefault && (
            <p className="text-[13px]" role="status">
              {t(isLiveDefault ? 'antigravity.models.current' : 'antigravity.models.pending')}
            </p>
          )}
        </>
      ) : (
        <p className="text-[13px]">{t('antigravity.models.empty')}</p>
      )}
      <p className="text-[13px] text-[var(--muted-foreground)]">
        {t('antigravity.models.applyHint')}
      </p>
      {message && (
        <p role="status" className="text-[13px]">
          {message}
        </p>
      )}
    </section>
  )
}

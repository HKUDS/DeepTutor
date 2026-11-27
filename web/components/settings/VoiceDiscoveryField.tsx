'use client'

import { useEffect, useRef, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useSettings } from '@/features/settings/store/SettingsStore'
import { apiFetch, apiUrl } from '@/lib/api'
import { modelTestFingerprint } from '@/lib/model-settings'
import type { VoiceChoice } from '@/lib/model-catalog-types'
import { inputClass, selectClass } from './shared'
import { registryButton } from './RegistryControls'

type Result = {
  status: 'ready' | 'unsupported'
  scope: 'account' | 'custom' | 'none'
  voices: VoiceChoice[]
}

export function VoiceDiscoveryField({
  profileId,
  modelId,
  value,
  update,
  disabled,
}: {
  profileId: string
  modelId: string
  value: string
  update: (value: string) => void
  disabled: boolean
}) {
  const { draft } = useSettings()
  // Changing a voice must not itself start another account lookup.
  const snapshot = structuredClone(draft)
  const model = snapshot.services.tts.profiles
    .find(p => p.id === profileId)
    ?.models.find(m => m.id === modelId)
  if (model) {
    const identity = {
      id: model.id,
      name: model.name,
      model: model.model,
      provider_ref: model.provider_ref,
    }
    Object.keys(model).forEach(key => {
      delete (model as unknown as Record<string, unknown>)[key]
    })
    Object.assign(model, identity)
  }
  const fingerprint = modelTestFingerprint(snapshot, 'tts', profileId, modelId)
  return (
    <VoiceLookup
      key={fingerprint}
      profileId={profileId}
      modelId={modelId}
      value={value}
      update={update}
      disabled={disabled}
    />
  )
}

function VoiceLookup({
  profileId,
  modelId,
  value,
  update,
  disabled,
}: {
  profileId: string
  modelId: string
  value: string
  update: (value: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const { draft } = useSettings()
  const catalog = useRef(draft)
  const hasModel = Boolean(
    draft.services.tts.profiles
      .find(p => p.id === profileId)
      ?.models.find(m => m.id === modelId)
      ?.model.trim()
  )
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [manual, setManual] = useState(false)
  useEffect(() => {
    if (!hasModel) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    let active = true
    const timeout = setTimeout(() => controller.abort(), 30000)
    setLoading(true)
    setError(false)
    setResult(null)
    const debounce = setTimeout(() => {
      void (async () => {
        try {
          const response = await apiFetch(apiUrl('/api/settings/voice/voices'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: controller.signal,
            body: JSON.stringify({
              catalog: catalog.current,
              profile_id: profileId,
              model_id: modelId,
            }),
          })
          if (!response.ok) throw new Error('Voice lookup failed')
          const data = (await response.json()) as Result
          if (!['ready', 'unsupported'].includes(data.status) || !Array.isArray(data.voices))
            throw new Error('Invalid voice response')
          if (active) setResult(data)
        } catch {
          if (active) setError(true)
        } finally {
          clearTimeout(timeout)
          if (active) setLoading(false)
        }
      })()
    }, 250)
    return () => {
      clearTimeout(debounce)
      active = false
      controller.abort()
      clearTimeout(timeout)
    }
  }, [profileId, modelId, attempt, hasModel])
  const listed = result?.voices.some(v => v.id === value)
  return (
    <section
      className="space-y-3 rounded-xl border border-[var(--border)] p-4"
      aria-label={t('Voice')}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium">{t('Voice')}</h4>
        <button
          type="button"
          disabled={loading || !hasModel}
          onClick={() => setAttempt(a => a + 1)}
          className={registryButton}
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {t(loading ? 'settings.voiceDiscovery.loading' : 'Refresh')}
        </button>
      </div>
      <p role="status" className="text-xs leading-relaxed text-[var(--muted-foreground)]">
        {t(
          !hasModel
            ? 'settings.voiceDiscovery.modelFirst'
            : loading
              ? 'settings.voiceDiscovery.loading'
              : error
                ? 'settings.voiceDiscovery.failed'
                : result?.status === 'unsupported'
                  ? 'settings.voiceDiscovery.unsupported'
                  : !result?.voices.length
                    ? 'settings.voiceDiscovery.empty'
                    : result.scope === 'custom'
                      ? 'settings.voiceDiscovery.custom'
                      : 'settings.voiceDiscovery.account'
        )}
      </p>
      {Boolean(result?.voices.length) && (
        <label className="block space-y-1.5 text-xs font-medium">
          <span>{t('settings.voiceDiscovery.choose')}</span>
          <select
            className={selectClass}
            disabled={disabled}
            value={listed ? value : ''}
            onChange={e => {
              if (e.target.value) update(e.target.value)
            }}
          >
            <option value="">{t('settings.voiceDiscovery.choose')}</option>
            {result?.voices.map(voice => (
              <option key={voice.id} value={voice.id}>
                {voice.label}
              </option>
            ))}
          </select>
        </label>
      )}
      {value && !listed && (
        <p className="break-all text-xs text-[var(--muted-foreground)]">
          {t('settings.voiceDiscovery.current')}: {value}
        </p>
      )}
      <button
        type="button"
        className="text-xs underline underline-offset-4"
        aria-expanded={manual}
        onClick={() => setManual(v => !v)}
      >
        {t('settings.voiceDiscovery.manual')}
      </button>
      {manual && (
        <label className="block space-y-1.5 text-xs font-medium">
          <span>{t('Voice ID')}</span>
          <input
            className={inputClass}
            value={value}
            disabled={disabled}
            onChange={e => update(e.target.value)}
          />
        </label>
      )}
    </section>
  )
}

'use client'

import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import type { CatalogModel, VoiceModelOption, VoiceOptions } from '@/lib/model-catalog-types'
import { RegistryField, RegistryModelIdField } from './RegistryControls'
import { inputClass, selectClass } from './shared'

export function VoiceModelFields({
  service,
  provider,
  model,
  options,
  preset,
  update,
  disabled,
}: {
  service: 'tts' | 'stt'
  provider: string
  model: CatalogModel
  options?: VoiceOptions
  preset?: VoiceModelOption
  update: (field: keyof CatalogModel, value: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const speedId = useId()
  const instructionId = useId()
  const voice = preset?.voices.find(v => v.id === model.voice)
  const languages =
    preset?.languages.filter(l => !voice?.languages || voice.languages.includes(l.id)) ?? []
  return (
    <section aria-label={t('Speech options')} className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        {service === 'tts' && (
          <>
            <label className="space-y-1.5 text-xs font-medium">
              <span className="block">{t('Suggested voice')}</span>
              <select
                className={selectClass}
                disabled={disabled}
                value={voice?.id ?? ''}
                onChange={e => {
                  const selected = preset?.voices.find(v => v.id === e.target.value)
                  if (!selected) return
                  update('voice', selected.id)
                  if (
                    model.language &&
                    selected.languages &&
                    !selected.languages.includes(model.language)
                  )
                    update('language', '')
                }}
              >
                <option value="">{t('Custom voice ID')}</option>
                {preset?.voices.map(v => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <RegistryModelIdField
              label={t('Voice ID')}
              value={model.voice ?? ''}
              options={preset?.voices.map(v => v.id) ?? []}
              disabled={disabled}
              onChange={v => update('voice', v)}
              placeholder={t('Enter a preset or private voice ID')}
            />
            <RegistryModelIdField
              label={t('Response format')}
              value={model.response_format ?? ''}
              options={preset?.formats ?? []}
              disabled={disabled}
              onChange={v => update('response_format', v)}
              placeholder={preset?.formats[0] ?? 'mp3'}
            />
          </>
        )}
        {(service === 'stt' || Boolean(preset?.languages.length)) && (
          <RegistryModelIdField
            label={t('Speech language')}
            value={model.language ?? ''}
            disabled={disabled}
            options={languages.map(l => l.id)}
            onChange={v => update('language', v)}
            placeholder={t('Auto detect')}
          />
        )}
        {service === 'tts' && preset?.speed && (
          <div className="space-y-1.5">
            <label htmlFor={speedId} className="text-xs font-medium">
              {t('Speech speed')}
            </label>
            <input
              id={speedId}
              type="number"
              className={inputClass}
              disabled={disabled}
              value={model.speed ?? ''}
              min={preset.speed.min}
              max={preset.speed.max}
              step={preset.speed.step}
              placeholder="1.0"
              onChange={e => update('speed', e.target.value)}
            />
            <p className="text-xs text-[var(--muted-foreground)]">
              {preset.speed.min}–{preset.speed.max}×
            </p>
          </div>
        )}
        {service === 'tts' && preset?.sample_rates && (
          <RegistryModelIdField
            label={t('Sample rate (Hz)')}
            value={model.sample_rate ?? ''}
            disabled={disabled}
            options={preset.sample_rates.map(String)}
            placeholder="24000"
            onChange={v => update('sample_rate', v)}
          />
        )}
        {service === 'stt' && provider === 'volcengine_speech' && (
          <RegistryField
            label={t('Speech resource ID')}
            value={model.resource_id ?? ''}
            disabled={disabled}
            placeholder="volc.bigasr.auc_turbo"
            onChange={v => update('resource_id', v)}
          />
        )}
      </div>
      {service === 'tts' && preset?.instructions && (
        <div className="space-y-1.5">
          <label htmlFor={instructionId} className="text-xs font-medium">
            {t('Voice instructions')}
          </label>
          <textarea
            id={instructionId}
            className={inputClass}
            disabled={disabled}
            rows={2}
            value={model.instructions ?? ''}
            onChange={e => update('instructions', e.target.value)}
            placeholder={t('For example: speak warmly and slowly.')}
          />
        </div>
      )}
      {voice?.languages && (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t('Voice languages')}: {voice.languages.join(', ')}
        </p>
      )}
      {!preset?.languages.length && service === 'tts' && (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t(preset?.language_note ?? 'Language follows the text and selected voice.')}
        </p>
      )}
      {service === 'tts' && provider === 'volcengine_speech' && (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t(
            'Doubao TTS uses the model resource ID to select a version. Use a voice from that version and a Speech API key, not an Ark key.'
          )}
        </p>
      )}
      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
        {t(
          'Suggestions depend on the provider and model. You can enter other model, voice and language IDs supported by your account.'
        )}
        {options?.docs_url && (
          <>
            {' '}
            <a
              href={options.docs_url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-4"
            >
              {t('Provider voice documentation')}
            </a>
          </>
        )}
      </p>
    </section>
  )
}

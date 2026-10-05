'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { nativeSelectClass, selectOptionClass } from '@/components/settings/shared'
import { listLLMOptions, type LLMOption } from '@/lib/llm-options'

type Selection = { profile_id: string; model_id: string }

export function ImageDescriptionModelSetting({
  value,
  disabled,
  onChange,
}: {
  value: Selection | null
  disabled: boolean
  onChange: (selection: Selection | null) => void
}) {
  const { t } = useTranslation()
  const [models, setModels] = useState<LLMOption[]>([])
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    listLLMOptions().then(
      result => {
        if (active) setModels(result.options.filter(model => model.supports_vision))
      },
      () => {
        if (active) setFailed(true)
      }
    )
    return () => {
      active = false
    }
  }, [])

  const key = (selection: Selection) => JSON.stringify([selection.profile_id, selection.model_id])
  const selected = value ? key(value) : ''
  const missing = value && !models.some(model => key(model) === selected)

  return (
    <section className="mb-10">
      <label htmlFor="image-description-model" className="mb-2 block text-[13px] font-medium">
        {t('Image description model')}
      </label>
      <select
        id="image-description-model"
        className={nativeSelectClass}
        disabled={disabled}
        value={selected}
        onChange={event => {
          const model = models.find(item => key(item) === event.target.value)
          onChange(model ? { profile_id: model.profile_id, model_id: model.model_id } : null)
        }}
      >
        <option value="" className={selectOptionClass}>
          {t('Use main LLM (fallback)')}
        </option>
        {missing && (
          <option value={selected} disabled>
            {t('Selected model unavailable')}
          </option>
        )}
        {models.map(model => (
          <option key={key(model)} value={key(model)} className={selectOptionClass}>
            {model.profile_name} / {model.model_name}
          </option>
        ))}
      </select>
      <p className="mt-2 text-xs text-[var(--muted-foreground)]">
        {t(
          'Select a vision model for image descriptions in documents.'
        )}
      </p>
      {failed && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {t('Failed to load image description models.')}
        </p>
      )}
    </section>
  )
}

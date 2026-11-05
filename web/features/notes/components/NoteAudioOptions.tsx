'use client'

import { useTranslation } from 'react-i18next'
export default function NoteAudioOptions({
  value,
  disabled,
  onChange,
}: {
  value: Record<string, unknown>
  disabled?: boolean
  onChange: (value: Record<string, unknown>) => void
}) {
  const { t } = useTranslation()
  return (
    <fieldset disabled={disabled} className="dt-note-audio-options">
      {(['host_voice', 'expert_voice'] as const).map((key, i) => (
        <label key={key}>
          {t(i ? 'Expert voice' : 'Host voice')}
          <input
            value={String(value[key] || '')}
            placeholder={t('Voice ID from your speech provider')}
            onChange={e => onChange({ ...value, [key]: e.target.value })}
          />
        </label>
      ))}
      <label>
        {t('Duration (minutes)')}
        <select
          value={Number(value.target_minutes) || 1}
          onChange={e => onChange({ ...value, target_minutes: Number(e.target.value) })}
        >
          {[1, 3, 5, 10, 15].map(n => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
    </fieldset>
  )
}

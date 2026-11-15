'use client'

import { useTranslation } from 'react-i18next'
import type { CatalogModel } from '@/lib/model-catalog-types'
import {
  VALID_REASONING_EFFORTS,
  configuredReasoningLevels,
  reasoningEffortOptions,
  reasoningEffortOptionsFromSupportedLevels,
} from '@/lib/reasoning-effort'

export default function ReasoningLevelSettings({
  model,
  binding,
  onDefaultChange,
  onToggle,
}: {
  binding?: string
  onDefaultChange?: (value: string) => void
  model: CatalogModel
  onToggle: (level: string) => void
}) {
  const { t } = useTranslation()
  const defaults = Array.isArray(model.codex_supported_reasoning_levels)
    ? reasoningEffortOptionsFromSupportedLevels(model.codex_supported_reasoning_levels)
    : reasoningEffortOptions(binding, model.model, model.reasoning_effort, model.capabilities?.reasoning)
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-[12px] font-medium text-[var(--foreground)]">
        {t('Enabled reasoning levels')}
      </legend>
      <div className="flex flex-wrap gap-1.5">
        {reasoningEffortOptionsFromSupportedLevels([...VALID_REASONING_EFFORTS])
          .filter(item => item.value)
          .map(item => {
            const enabled = configuredReasoningLevels(model, binding)
            const supported = model.codex_supported_reasoning_levels
            const unavailable =
              model.capabilities?.reasoning === false ||
              (Array.isArray(supported) && !supported.includes(item.value))
            return (
              <label
                key={item.value}
                className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-2 text-[12px] transition-colors motion-reduce:transition-none ${enabled.includes(item.value) && !unavailable ? 'border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]' : 'border-[var(--border)] text-[var(--muted-foreground)]'} ${unavailable ? 'cursor-not-allowed opacity-40' : 'hover:border-[var(--primary)]'}`}
              >
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 accent-[var(--primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
                  checked={enabled.includes(item.value) && !unavailable}
                  disabled={unavailable}
                  onChange={() => onToggle(item.value)}
                />
                {t(item.label)}
              </label>
            )
          })}
      </div>
      {onDefaultChange && <details className="mt-3 text-xs text-[var(--muted-foreground)]">
        <summary className="cursor-pointer">{t('Other tasks: default reasoning')}</summary>
        <label className="mt-2 block">
          {t('Provider reasoning mode')}
          <select aria-label={t('Provider reasoning mode')} value={model.reasoning_effort || ''} onChange={e => onDefaultChange(e.target.value)} className="mt-1 block w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-2">
            {defaults.map(item => <option key={item.value} value={item.value}>{t(item.label)}</option>)}
          </select>
        </label>
      </details>}
      <p className="mt-2 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          'Enable the levels your model accepts, then choose one in chat. No selection uses the provider default.'
        )}
      </p>
    </fieldset>
  )
}

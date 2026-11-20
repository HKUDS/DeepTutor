'use client'

import { useEffect, useId, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { getPageIndexConfig, updatePageIndexConfig } from '@/features/knowledge/api/engines'

export default function PageIndexOssSettingsForm({
  onChanged,
  onError,
}: {
  onChanged?: () => void
  onError?: (message: string) => void
}) {
  const { t } = useTranslation()
  const inputId = useId()
  const [value, setValue] = useState('')
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getPageIndexConfig({ force: true })
      .then(config => {
        if (cancelled) return
        setValue(config.oss_summary_concurrency?.toString() ?? '')
        setLoaded(true)
      })
      .catch(err => {
        if (cancelled) return
        const message = err instanceof Error ? err.message : String(err)
        setError(message)
        onError?.(message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // Read once when this engine's settings form mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async (event: FormEvent) => {
    event.preventDefault()
    const limit = value.trim() === '' ? null : Number(value)
    if (limit !== null && (!Number.isInteger(limit) || limit < 1 || limit > 128)) {
      setError(t('Enter a whole number from 1 to 128, or leave blank.'))
      return
    }
    setSaving(true)
    setError(null)
    try {
      const config = await updatePageIndexConfig({ oss_summary_concurrency: limit })
      setValue(config.oss_summary_concurrency?.toString() ?? '')
      onChanged?.()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      onError?.(message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={event => void save(event)} className="space-y-4">
      <div>
        <label htmlFor={inputId} className="mb-1 block text-[12px] font-medium">
          {t('Flash concurrency per stage')}
        </label>
        <input
          id={inputId}
          type="number"
          min={1}
          max={128}
          step={1}
          value={value}
          onChange={event => setValue(event.target.value)}
          disabled={loading || saving || !loaded}
          placeholder={t('SDK default (64)')}
          aria-describedby={`${inputId}-help`}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--foreground)]/25 disabled:opacity-50"
        />
        <p
          id={`${inputId}-help`}
          className="mt-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]"
        >
          {t(
            'Flash only. Summary and expansion stages each use this limit and may run together. Leave blank for the SDK default.'
          )}
        </p>
      </div>
      {error && (
        <p role="alert" className="text-[12px] text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={loading || saving || !loaded}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
      >
        {(loading || saving) && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {t('Save changes')}
      </button>
    </form>
  )
}

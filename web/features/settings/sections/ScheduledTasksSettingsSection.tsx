'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  inputClass,
} from '@/components/settings/shared'
import { useSettings } from '@/features/settings/store/SettingsStore'
import { apiFetch, apiUrl } from '@/lib/api'
import { EXTENSION_ENDPOINTS } from '@/lib/settings-extensions'

type ScheduledTasksSettings = {
  enabled: boolean
  check_interval_s: number
}

type ScheduledTasksPayload = {
  settings: ScheduledTasksSettings
  bounds: { check_interval_s: [number, number] }
}

export default function ScheduledTasksSettingsSection() {
  const { t } = useTranslation()
  const { registerExtension, pendingExtensionPayload, draftRevision } = useSettings()
  const [payload, setPayload] = useState<ScheduledTasksPayload | null>(null)
  const [draft, setDraft] = useState<ScheduledTasksSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const response = await apiFetch(apiUrl(EXTENSION_ENDPOINTS['cron-scheduler']))
        const data = (await response.json().catch(() => ({}))) as
          ScheduledTasksPayload | { detail?: string }
        if (!response.ok) {
          throw new Error(
            'detail' in data && data.detail
              ? String(data.detail)
              : t('Failed to load scheduled-task settings.')
          )
        }
        if (cancelled) return
        const next = data as ScheduledTasksPayload
        setPayload(next)
        // An edit left behind earlier in this session (or parked in a saved
        // draft) wins over the server value — leaving the page is not a way
        // to discard changes.
        const pending = pendingExtensionPayload('cron-scheduler') as
          ScheduledTasksSettings | undefined
        setDraft(pending ? { ...pending } : { ...next.settings })
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [draftRevision, pendingExtensionPayload, t])

  const dirty = useMemo(
    () =>
      Boolean(
        payload &&
        draft &&
        (payload.settings.enabled !== draft.enabled ||
          payload.settings.check_interval_s !== draft.check_interval_s)
      ),
    [draft, payload]
  )

  // Flush through the global Apply (top toolbar) instead of a local button.
  const draftRef = useRef(draft)
  draftRef.current = draft
  const save = useCallback(async () => {
    const current = draftRef.current
    if (!current) return
    setError(null)
    try {
      const response = await apiFetch(apiUrl(EXTENSION_ENDPOINTS['cron-scheduler']), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(current),
      })
      const data = (await response.json().catch(() => ({}))) as
        ScheduledTasksPayload | { detail?: string }
      if (!response.ok) {
        throw new Error(
          'detail' in data && data.detail
            ? String(data.detail)
            : t('Failed to save scheduled-task settings.')
        )
      }
      const next = data as ScheduledTasksPayload
      setPayload(next)
      setDraft({ ...next.settings })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      throw err
    }
  }, [t])

  useEffect(() => {
    registerExtension('cron-scheduler', { dirty, save, payload: draft })
    return () => registerExtension('cron-scheduler', null)
  }, [dirty, draft, save, registerExtension])

  const bounds = payload?.bounds.check_interval_s
  const intervalDisabled = draft ? !draft.enabled : false

  return (
    <div>
      <SettingsPageHeader
        title={t('Scheduled tasks')}
        description={t(
          'Control the built-in scheduler that runs reminders and other scheduled jobs. Jobs only call the model when they are due.'
        )}
      />

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('Loading scheduled-task settings...')}
        </div>
      )}

      {!loading && error && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}

      {!loading && payload && draft && (
        <SettingSection
          title={t('Scheduler')}
          description={t(
            'Turning this off stops the periodic scheduler entirely — due jobs stay dormant until it is turned back on, so a quiet deployment consumes no provider quota on a timer.'
          )}
        >
          <SettingRow
            title={t('Enable scheduled tasks')}
            description={t(
              'Applies immediately; no restart needed. Jobs that came due while disabled run once when re-enabled.'
            )}
            control={
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--foreground)]"
                checked={draft.enabled}
                onChange={event =>
                  setDraft(current =>
                    current ? { ...current, enabled: event.target.checked } : current
                  )
                }
              />
            }
          />
          <SettingRow
            title={t('Idle re-check interval (seconds)')}
            description={t(
              'How often the scheduler re-checks the job store when nothing is due. Individual job schedules are unaffected.'
            )}
            control={
              <input
                className={`${inputClass} w-28`}
                type="number"
                min={bounds?.[0] ?? 5}
                max={bounds?.[1] ?? 86400}
                disabled={intervalDisabled}
                value={draft.check_interval_s}
                onChange={event =>
                  setDraft(current =>
                    current
                      ? {
                          ...current,
                          check_interval_s: Number(event.target.value),
                        }
                      : current
                  )
                }
              />
            }
          />
        </SettingSection>
      )}
    </div>
  )
}

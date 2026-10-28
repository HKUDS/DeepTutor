'use client'

import { useModules } from '@/hooks/useModules'
import { browserStorage } from '@/shared/storage'
import { useEffect, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuthStatus } from '@/hooks/useAuthStatus'
import { notify } from '@/lib/notifications'
import { startCalendarSync, useCalendarRevision } from '../store/calendar-store'
import { listOccurrences } from '../transport/api'
import { browserTimeZone, formatTime } from '../model/dates'

/** Reminders work anywhere in the signed-in app while a tab is open. */
export default function CalendarRuntime({ children }: { children: ReactNode }) {
  const { t, i18n } = useTranslation()
  const { loading, learningPolicy, enabled: authEnabled, authenticated } = useAuthStatus()
  const { modules } = useModules()
  const enabled =
    Boolean(modules?.some(module => module.id === 'calendar' && module.enabled)) &&
    !loading &&
    (!authEnabled || authenticated) &&
    (!learningPolicy || learningPolicy.allowedSurfaces.includes('chat'))
  const revision = useCalendarRevision()
  useEffect(() => {
    if (enabled) return startCalendarSync()
  }, [enabled])
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let running = false
    const check = async () => {
      if (running) return
      running = true
      try {
        const now = Date.now()
        const result = await listOccurrences(
          {
            start: new Date(now - 86400_000).toISOString(),
            end: new Date(now + 29 * 86400_000).toISOString(),
            tz: browserTimeZone(),
          },
          controller.signal
        )
        if (controller.signal.aborted) return
        for (const occurrence of result.occurrences) {
          const start = new Date(occurrence.start).getTime()
          for (const [index, minutes] of occurrence.reminders.entries()) {
            const due = new Date(occurrence.reminder_times[index]).getTime()
            if (!Number.isFinite(due)) continue
            if (due > now || due < now - 90_000) continue
            const deliver = () => {
              if (controller.signal.aborted) return
              const key = 'deeptutor.calendar.reminders'
              let seen: Record<string, number> = {}
              try {
                seen = JSON.parse(browserStorage.readRaw('local', key) ?? '{}')
              } catch {}
              const id = `${occurrence.id}:${occurrence.start}:${minutes}`
              if (seen[id]) return
              seen = Object.fromEntries(
                Object.entries(seen).filter(([, time]) => time > now - 2 * 86400_000)
              )
              seen[id] = now
              try {
                browserStorage.writeRaw('local', key, JSON.stringify(seen))
              } catch {}
              const title = occurrence.title || t('(No title)')
              const message = occurrence.all_day
                ? title
                : `${title} · ${formatTime(new Date(start), i18n.language)}`
              notify(message, { durationMs: 15000 })
              if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                try {
                  const notification = new Notification(title, { body: message, tag: id })
                  notification.onclick = () => {
                    window.focus()
                    notification.close()
                  }
                } catch {}
              }
            }
            if (navigator.locks)
              await navigator.locks.request('deeptutor-calendar-reminder', deliver)
            else deliver()
          }
        }
      } catch {
        /* Network failures retry on focus or the next tick. */
      } finally {
        running = false
      }
    }
    void check()
    const timer = setInterval(() => void check(), 30_000)
    const focus = () => void check()
    window.addEventListener('focus', focus)
    return () => {
      controller.abort()
      clearInterval(timer)
      window.removeEventListener('focus', focus)
    }
  }, [revision, t, i18n.language, enabled])
  return children
}

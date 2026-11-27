'use client'

import { useCallback, useEffect, useState } from 'react'
import { readClientCache, withClientCache } from '@/lib/client-cache'
import { usePathname } from 'next/navigation'
import { apiFetch, apiUrl } from '@/lib/api'
import { subscribeSessionChanges } from '@/lib/session-events'
import type { LearningKind, LearningSources } from '@/lib/learning-dashboard'

const CACHE_KEY = 'navigation:learning-index'
type LearningIndex = { sources: LearningSources; failed: LearningKind[] }
const EMPTY: LearningSources = { books: [], mastery: [], reading: [], watching: [], practice: [] }
export function useLearningIndex(enabled = true) {
  const pathname = usePathname()
  const [sources, setSources] = useState<LearningSources>(
    () => readClientCache<LearningIndex>(CACHE_KEY)?.sources ?? EMPTY
  )
  const [failed, setFailed] = useState<LearningKind[]>(
    () => readClientCache<LearningIndex>(CACHE_KEY)?.failed ?? []
  )
  const [loading, setLoading] = useState(() => !readClientCache<LearningIndex>(CACHE_KEY))
  const [revision, setRevision] = useState(0)
  const retry = useCallback(() => setRevision(value => value + 1), [])
  useEffect(() => {
    if (!enabled) return
    let alive = true
    let busy = false
    const refresh = async () => {
      if (busy || document.visibilityState === 'hidden') return
      busy = true
      try {
        const payload = await withClientCache(
          CACHE_KEY,
          async () => {
            const response = await apiFetch(
              apiUrl('/api/dashboard/learning-index'),
              {
                signal: AbortSignal.timeout(20000),
              }
            )
            if (!response.ok) throw new Error('Learning index unavailable')
            return (await response.json()) as LearningIndex
          },
          { force: true }
        )
        if (alive) {
          // Keep readable collections during a transient partial outage.
          setSources(
            previous =>
              Object.fromEntries(
                Object.keys(EMPTY).map(key => {
                  const kind = key as LearningKind
                  const rows = payload.sources[kind] ?? []
                  return [
                    kind,
                    payload.failed.includes(kind) && !rows.length ? previous[kind] : rows,
                  ]
                })
              ) as unknown as LearningSources
          )
          setFailed(payload.failed)
        }
      } catch {
        if (alive) setFailed(Object.keys(EMPTY) as LearningKind[])
      } finally {
        if (alive) setLoading(false)
        busy = false
      }
    }
    void refresh()
    const unsubscribe = subscribeSessionChanges(() => void refresh())
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    const timer = window.setInterval(refresh, 30000)
    return () => {
      alive = false
      unsubscribe()
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [enabled, pathname, revision])
  return { sources, failed, loading, retry }
}

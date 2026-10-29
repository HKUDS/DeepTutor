'use client'
import { useCallback, useEffect, useState } from 'react'
import { readClientCache, withClientCache } from '@/lib/client-cache'
import { usePathname } from 'next/navigation'
import { apiFetch, apiUrl } from '@/lib/api'
import { subscribeSessionChanges } from '@/lib/session-events'
import type { PartnerInfo } from '@/lib/partners-api'
import type { PartnerGroup } from '@/lib/partner-groups-api'
export interface PartnerNavigationSession {
  kind: 'partner' | 'group'
  owner_id: string
  owner_name: string
  session_key: string
  title: string
  updated_at: number
}
export interface PartnerNavigationData {
  partners: Pick<
    PartnerInfo,
    'partner_id' | 'name' | 'description' | 'emoji' | 'avatar' | 'color' | 'running' | 'can_manage'
  >[]
  groups: PartnerGroup[]
  sessions: PartnerNavigationSession[]
  unavailable: string[]
}
const CACHE_KEY = 'navigation:partners'
export function usePartnerNavigation(enabled: boolean) {
  const pathname = usePathname()
  const [data, setData] = useState<PartnerNavigationData>(
    () =>
      readClientCache<PartnerNavigationData>(CACHE_KEY) ?? {
        partners: [],
        groups: [],
        sessions: [],
        unavailable: [],
      }
  )
  const [loading, setLoading] = useState(() => !readClientCache<PartnerNavigationData>(CACHE_KEY))
  const [error, setError] = useState(false)
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
        const next = await withClientCache(
          CACHE_KEY,
          async () => {
            const response = await apiFetch(apiUrl('/api/partners/navigation'), {
              signal: AbortSignal.timeout(20000),
            })
            if (!response.ok) throw new Error('Partner navigation unavailable')
            return (await response.json()) as PartnerNavigationData
          },
          { force: true }
        )
        if (alive) {
          setData(next)
          setError(false)
        }
      } catch {
        if (alive) setError(true)
      } finally {
        busy = false
        if (alive) setLoading(false)
      }
    }
    void refresh()
    const unsubscribe = subscribeSessionChanges(() => void refresh())
    const timer = window.setInterval(refresh, 15000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      alive = false
      unsubscribe()
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [enabled, pathname, revision])
  return { data, loading, error, retry }
}

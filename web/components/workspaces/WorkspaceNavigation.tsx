'use client'

import { Suspense, useEffect } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { listWorkspaces } from '@/lib/workspaces-api'
import {
  activeWorkspaceId,
  registerWorkspaceNavigator,
  rememberWorkspaceId,
  scopedUrl,
  selectWorkspace,
  workspaceIdOf,
} from '@/lib/workspace-scope'

/**
 * Write the tab's workspace into any URL that arrived without one, so the
 * address can be copied and every query-reading surface sees the same scope.
 * A remembered workspace that no longer exists falls back to General once.
 */
function ScopeCanonicalizer() {
  const router = useRouter()
  const pathname = usePathname()
  const query = useSearchParams()
  const named = workspaceIdOf(query)
  useEffect(() => {
    if (named !== null) {
      rememberWorkspaceId(named)
      return
    }
    router.replace(scopedUrl(`${window.location.pathname}${window.location.search}${window.location.hash}`))
  }, [named, pathname, router])
  useEffect(() => {
    const remembered = activeWorkspaceId()
    if (!remembered) return
    let alive = true
    listWorkspaces()
      .then(rows => {
        if (!alive || rows.some(row => row.workspace_id === remembered && row.kind === 'workspace')) return
        rememberWorkspaceId('')
        void selectWorkspace('', `/${window.location.pathname.split('/')[1] || 'chat'}`)
      })
      .catch(() => undefined)
    return () => { alive = false }
  }, [])
  return null
}

/** Cross-store navigation disposes client runtimes. Only a link that names a workspace leaves this one. */
export function WorkspaceNavigation() {
  const router = useRouter()
  useEffect(() => registerWorkspaceNavigator(router.push), [router])
  useEffect(() => {
    const follow = (event: MouseEvent) => {
      const anchor = (event.target as Element).closest?.('a[href]') as HTMLAnchorElement | null
      if (!anchor || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
          event.button !== 0 || anchor.target === '_blank' || anchor.hasAttribute('download')) return
      const url = new URL(anchor.href)
      if (url.origin !== window.location.origin) return
      const target = workspaceIdOf(url.searchParams)
      if (target !== null && target !== activeWorkspaceId()) {
        event.preventDefault()
        event.stopImmediatePropagation()
        void selectWorkspace(target, url.toString())
      }
    }
    document.addEventListener('click', follow, true)
    return () => document.removeEventListener('click', follow, true)
  }, [])
  return (
    <Suspense>
      <ScopeCanonicalizer />
    </Suspense>
  )
}

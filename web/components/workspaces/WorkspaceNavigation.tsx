'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { activeWorkspaceId, registerWorkspaceNavigator, selectWorkspace } from '@/lib/workspace-scope'

/** Cross-store navigation disposes client runtimes. Links own their scope explicitly. */
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
      const target = url.searchParams.get('dt_workspace') ?? url.searchParams.get('workspace') ?? ''
      if (target !== activeWorkspaceId()) {
        event.preventDefault()
        event.stopImmediatePropagation()
        void selectWorkspace(target, url.toString())
      }
    }
    document.addEventListener('click', follow, true)
    return () => document.removeEventListener('click', follow, true)
  }, [])
  return null
}

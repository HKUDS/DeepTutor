'use client'

import { Fragment, useEffect, type ReactNode } from 'react'
import { useSearchParams } from 'next/navigation'
import { resetReadingTurnState } from '@/lib/reading-turn-state'

function ScopeLifetime({ children }: { children: ReactNode }) {
  useEffect(() => () => {
    resetReadingTurnState()
  }, [])
  return children
}

/** Reset content state even for query-only navigation and browser back/forward. */
export function WorkspaceRuntimeBoundary({ children }: { children: ReactNode }) {
  const query = useSearchParams()
  const workspaceId = query.get('dt_workspace') ?? query.get('workspace') ?? ''
  return <Fragment key={workspaceId}><ScopeLifetime>{children}</ScopeLifetime></Fragment>
}

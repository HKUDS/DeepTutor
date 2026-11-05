'use client'

import { Fragment, useEffect, type ReactNode } from 'react'
import { useActiveWorkspaceId } from '@/hooks/useActiveWorkspaceId'
import { resetReadingTurnState } from '@/lib/reading-turn-state'

function ScopeLifetime({ children }: { children: ReactNode }) {
  useEffect(() => () => {
    resetReadingTurnState()
  }, [])
  return children
}

/** Reset content state even for query-only navigation and browser back/forward. */
export function WorkspaceRuntimeBoundary({ children }: { children: ReactNode }) {
  const workspaceId = useActiveWorkspaceId()
  return <Fragment key={workspaceId}><ScopeLifetime>{children}</ScopeLifetime></Fragment>
}

'use client'

import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { transferWorkspaceDraft } from '@/lib/workspace-drafts'
import { updateSessionOrganization } from '@/lib/session-api'
import { selectWorkspace as navigateWorkspace } from '@/lib/workspace-scope'

type BindingState = { sessionKey: string; sessionId: string | null; isStreaming: boolean }

/** Persist a move before changing its source session, even if navigation occurs meanwhile. */
export function useWorkspaceBinding(
  state: BindingState,
  configureSession: (patch: { workspaceId: string | null }, key: string) => void,
) {
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [pendingKey, setPendingKey] = useState<string | null>(null)
  const pending = useRef(new Set<string>())
  const currentState = useRef(state)
  const mounted = useRef(true)
  useLayoutEffect(() => { currentState.current = state }, [state])
  useLayoutEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const selectWorkspace = useCallback((workspaceId: string) => {
    const key = state.sessionKey
    const sid = state.sessionId
    if (state.isStreaming || pending.current.has(key)) return
    setFailure(null)
    const apply = () => configureSession({ workspaceId: workspaceId || null }, key)
    if (!sid) {
      // The destination URL creates the draft in its scope after navigation.
      // Do not rebind the source runtime before its draft has been saved.
      void navigateWorkspace(workspaceId, '/chat', { beforeNavigate: () => transferWorkspaceDraft(workspaceId) })
      return
    }
    pending.current.add(key)
    setPendingKey(key)
    void updateSessionOrganization(sid, { workspace_id: workspaceId || null })
      .then(() => {
        apply()
        if (mounted.current && currentState.current.sessionKey === key) {
          void navigateWorkspace(workspaceId, `/chat/${encodeURIComponent(sid)}`)
        }
      })
      .catch((err: unknown) => setFailure({ key, message: err instanceof Error ? err.message : String(err) }))
      .finally(() => {
        pending.current.delete(key)
        setPendingKey(current => current === key ? null : current)
      })
  }, [configureSession, state.isStreaming, state.sessionId, state.sessionKey])
  return {
    selectWorkspace,
    error: failure?.key === state.sessionKey ? failure.message : '',
    pending: pendingKey === state.sessionKey,
  }
}

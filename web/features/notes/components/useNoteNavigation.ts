'use client'

import { useEffect, useState } from 'react'
import { activeWorkspaceId } from '@/lib/workspace-scope'
import type { NotePage, NoteSummary } from '@/lib/notes-api'

type Destination = {
  doc?: NotePage
  pages: NoteSummary[]
  treeOpen?: boolean
  workspace: string
  Editor?: typeof import('./NoteEditor').default
}

// Used only for the first render of the destination in the same workspace.
let pending: Destination | null = null

export function prepareNoteDestination(destination: Destination) {
  pending = destination
}

export function useNoteDestination(id?: string) {
  const [initial] = useState(() =>
    pending && pending.doc?.id === id && pending.workspace === activeWorkspaceId() ? pending : null
  )
  useEffect(() => {
    if (pending === initial) pending = null
  }, [initial])
  return initial
}

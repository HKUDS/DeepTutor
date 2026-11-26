'use client'

import { useEffect, useState } from 'react'
import { activeWorkspaceId } from '@/lib/workspace-scope'
import { browserStorage } from '@/shared/storage'
import type { NoteBlock, NotePage, NoteSummary } from '@/lib/notes-api'

type Draft = { title: string; blocks: NoteBlock[]; revision: number }

export function noteDraftKey(owner: string, docId: string) {
  return `deeptutor.notes.draft:${owner}:${docId}`
}

export function restoreNoteDraft(doc: NotePage, key: string) {
  const raw = browserStorage.readRaw('local', key)
  if (raw) {
    try {
      const draft: Draft = JSON.parse(raw)
      if (Array.isArray(draft.blocks)) {
        if (draft.revision === doc.revision)
          return { doc: { ...doc, title: draft.title, blocks: draft.blocks }, restored: true }
        return { doc, conflict: draft }
      }
    } catch {
      /* Ignore invalid recovery data, never overwrite the server page. */
    }
  }
  return { doc }
}

type Destination = {
  owner?: string
  restored?: boolean
  conflict?: Draft
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

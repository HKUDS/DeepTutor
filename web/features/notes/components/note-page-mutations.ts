import { deleteCoWriterDocument } from '@/lib/co-writer-api'
import { getNote, type NotePage, type NoteSummary } from '@/lib/notes-api'

import { noteDraftKey, restoreNoteDraft } from './useNoteNavigation'

type Target = NotePage | NoteSummary

export async function deleteNotePage(target: Target, current: NotePage) {
  await deleteCoWriterDocument(target.id)
  // The store promotes direct children and increments their revision.
  return current.parent_id === target.id
    ? { ...current, parent_id: target.parent_id, revision: current.revision + 1 }
    : null
}

export async function loadDestination(
  target: Target,
  pages: NoteSummary[],
  treeOpen: boolean,
  workspace: string,
  owner: string | null
) {
  const remaining = pages.filter(p => p.id !== target.id).map(p =>
    p.parent_id === target.id ? { ...p, parent_id: target.parent_id, revision: p.revision + 1 } : p
  )
  const parent = target.parent_id ? await getNote(target.parent_id).catch(() => null) : null
  const Editor = parent ? (await import('./NoteEditor')).default : undefined
  return {
    pages: remaining,
    workspace,
    ...(parent && owner ? { ...restoreNoteDraft(parent, noteDraftKey(owner, parent.id)), owner } : { doc: parent ?? undefined }),
    Editor,
    treeOpen,
  }
}

import { deleteCoWriterDocument } from '@/lib/co-writer-api'
import { getNote, saveNote, type NotePage, type NoteSummary } from '@/lib/notes-api'
import type { PageAction } from './NotePageActions'

type Target = NotePage | NoteSummary

export async function applyPageAction(target: Target, action: PageAction, current: NotePage) {
  if (action === 'delete') {
    await deleteCoWriterDocument(target.id)
    // The store promotes direct children and increments their revision.
    return current.parent_id === target.id
      ? { ...current, parent_id: target.parent_id, revision: current.revision + 1 }
      : null
  }
  const updated = await saveNote(target.id, {
    archived: action === 'archive',
    expected_revision: current.id === target.id ? current.revision : target.revision,
  })
  return current.id === target.id ? updated : null
}

export async function loadDestination(
  target: Target,
  action: PageAction,
  pages: NoteSummary[],
  treeOpen: boolean,
  workspace: string
) {
  const remaining =
    action === 'archive'
      ? pages.map(p => (p.id === target.id ? { ...p, archived: true } : p))
      : pages
          .filter(p => p.id !== target.id)
          .map(p =>
            p.parent_id === target.id
              ? { ...p, parent_id: target.parent_id, revision: p.revision + 1 }
              : p
          )
  const parent = target.parent_id ? await getNote(target.parent_id).catch(() => null) : null
  const Editor = parent ? (await import('./NoteEditor')).default : undefined
  return {
    pages: remaining,
    workspace,
    doc: parent ?? undefined,
    Editor,
    treeOpen,
  }
}

import type { useRouter } from 'next/navigation'
import { notifyCoWriterChanged } from '@/lib/co-writer-events'
import { activeWorkspaceId, scopedUrl } from '@/lib/workspace-scope'
import { deleteCoWriterDocument } from '@/lib/co-writer-api'
import { createNote, getNote, saveNote, type NotePage, type NoteSummary } from '@/lib/notes-api'

import { noteDraftKey, prepareNoteDestination, restoreNoteDraft, type NoteTreeView } from './useNoteNavigation'

type Target = NotePage | NoteSummary

export type PageAction = { open: string } | { create: string | null } | { remove: Target } | { pin: NoteSummary }

async function loadExistingPage(id: string, owner: string | null) {
  const [doc, { default: Editor }] = await Promise.all([getNote(id), import('./NoteEditor')])
  return owner
    ? { ...restoreNoteDraft(doc, noteDraftKey(owner, id)), owner, Editor }
    : { doc, Editor }
}

export async function applyPageAction(action: PageAction, {
  current, pages, treeOpen, treeView, workspace, owner, router, isMounted, updateChild, updatePinned, onPageRemoved, refreshPages,
}: {
  current: NotePage
  pages: NoteSummary[]
  treeOpen: boolean
  treeView: NoteTreeView
  workspace: string
  owner: string | null
  router: Pick<ReturnType<typeof useRouter>, 'push' | 'replace'>
  isMounted: () => boolean
  updateChild: (page: NotePage, bodyChanged: boolean) => void
  updatePinned: (page: NotePage) => void
  onPageRemoved?: (id: string) => void
  refreshPages: () => void
}) {
  const active = () => isMounted() && activeWorkspaceId() === workspace
  if (!active()) return false
  let destination: Parameters<typeof prepareNoteDestination>[0]
  if ('pin' in action) {
    const target = action.pin.id === current.id ? current : action.pin
    const updated = await saveNote(target.id, { pinned: !target.pinned, expected_revision: target.revision })
    if (active()) {
      if (target.id === current.id) updateChild(updated, false)
      updatePinned(updated)
    }
    notifyCoWriterChanged()
    return false
  }
  if ('open' in action) {
    destination = { ...await loadExistingPage(action.open, owner), pages, treeOpen, workspace }
  } else if ('create' in action) {
    const [doc, { default: Editor }] = await Promise.all([createNote('', action.create), import('./NoteEditor')])
    if (action.create) treeView.collapsed.delete(action.create)
    destination = { doc, Editor, pages: [{ ...doc, preview: '' }, ...pages], treeOpen, workspace }
  } else {
    const target = action.remove
    await deleteCoWriterDocument(target.id)
    notifyCoWriterChanged()
    if (!active()) return false
    if (target.id !== current.id) {
      // Another client may already have moved or edited this child.
      if (current.parent_id === target.id) {
        const child = await getNote(current.id)
        if (!active()) return false
        const bodyChanged = child.content !== current.content ||
          JSON.stringify(child.blocks) !== JSON.stringify(current.blocks)
        updateChild(child, bodyChanged)
      }
      refreshPages()
      return false
    }
    if (onPageRemoved) {
      onPageRemoved(target.id)
      return false
    }
    destination = await loadDestination(target, pages, treeOpen, workspace, owner)
  }
  if (!active()) return false
  prepareNoteDestination({ ...destination, treeView })
  const url = scopedUrl(destination.doc ? `/co-writer/${destination.doc.id}` : '/co-writer', workspace)
  if ('remove' in action) router.replace(url, { scroll: false })
  else router.push(url, { scroll: false })
  return true
}

async function loadDestination(
  target: Target,
  pages: NoteSummary[],
  treeOpen: boolean,
  workspace: string,
  owner: string | null
) {
  const remaining = pages.filter(p => p.id !== target.id).map(p =>
    p.parent_id === target.id ? { ...p, parent_id: target.parent_id } : p
  )
  const parent = target.parent_id
    ? await loadExistingPage(target.parent_id, owner).catch(() => null)
    : null
  return { ...parent, doc: parent?.doc, pages: remaining, workspace, treeOpen }
}

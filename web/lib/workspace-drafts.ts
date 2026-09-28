import { activeWorkspaceId } from './workspace-scope'
import { fetchAuthStatus } from './auth'

export type WorkspaceDraft = {
  text: string
  attachments: { filename: string; base64?: string; mimeType?: string }[]
}
async function key(workspaceId = activeWorkspaceId(), pathname = window.location.pathname): Promise<string> {
  const location = `${workspaceId}:${pathname}`
  const status = await fetchAuthStatus()
  if (!status || (status.enabled && (!status.authenticated || !status.user_id)))
    throw new Error('Account identity is unavailable for saving drafts.')
  return `${status.user_id || 'local-admin'}:${location}`
}

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('deeptutor-workspace-drafts', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('drafts')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function saveWorkspaceDraft(draft: WorkspaceDraft, workspaceId?: string, pathname?: string): Promise<void> {
  const draftKey = await key(workspaceId, pathname)
  const db = await database()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('drafts', 'readwrite')
      const store = tx.objectStore('drafts')
      if (draft.text || draft.attachments.length) store.put(draft, draftKey)
      else store.delete(draftKey)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}

export async function readWorkspaceDraft(workspaceId?: string, pathname?: string): Promise<WorkspaceDraft | undefined> {
  const draftKey = await key(workspaceId, pathname)
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('drafts', 'readonly')
      const store = tx.objectStore('drafts')
      const request = store.get(draftKey)
      tx.oncomplete = () => resolve(request.result)
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}

/** Move the current unsent message with an explicit composer assignment. */
export async function transferWorkspaceDraft(destination: string): Promise<void> {
  const source = activeWorkspaceId()
  if (source === destination) return
  const draft = await readWorkspaceDraft()
  if (!draft || (!draft.text && !draft.attachments.length)) return
  const prior = await readWorkspaceDraft(destination, '/chat')
  await saveWorkspaceDraft({
    text: [prior?.text, draft.text].filter(Boolean).join('\n\n'),
    attachments: [...(prior?.attachments || []), ...draft.attachments],
  }, destination, '/chat')
  await saveWorkspaceDraft({ text: '', attachments: [] })
}

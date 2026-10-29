import { browserStorage } from '@/shared/storage'

/**
 * The content workspace this tab is in.
 *
 * A URL that names a workspace (`dt_workspace`, including the empty value for
 * General) selects it; a URL that names none stays where the tab already is.
 * Links therefore never need to carry the scope to stay put, and leaving a
 * workspace is always an explicit act. A fresh tab resumes the last workspace
 * used in this browser.
 */
const STORAGE_KEY = 'deeptutor:workspace'

let remembered: string | null = null

function storedWorkspaceId(): string {
  remembered ??=
    browserStorage.readRaw('session', STORAGE_KEY) ?? browserStorage.readRaw('local', STORAGE_KEY) ?? ''
  return remembered
}

/** Record the scope a URL selected, for this tab and for the next fresh one. */
export function rememberWorkspaceId(workspaceId: string): void {
  if (remembered === workspaceId) return
  remembered = workspaceId
  // Unavailable storage (private mode) only costs the next fresh tab its resume.
  browserStorage.writeRaw('session', STORAGE_KEY, workspaceId)
  browserStorage.writeRaw('local', STORAGE_KEY, workspaceId)
}

/** The workspace a URL names explicitly, or null when it names none. */
export function workspaceIdOf(search: URLSearchParams): string | null {
  return search.get('dt_workspace') ?? search.get('workspace')
}

export function activeWorkspaceId(): string {
  if (typeof window === 'undefined') return ''
  const named = workspaceIdOf(new URLSearchParams(window.location.search))
  if (named !== null) {
    rememberWorkspaceId(named)
    return named
  }
  return storedWorkspaceId()
}

export function scopedUrl(path: string, workspaceId = activeWorkspaceId()): string {
  // Never attach local identity to third-party URLs (including signed media).
  const origin = typeof window === 'undefined' ? 'http://workspace.local' : window.location.origin
  if (path.startsWith('//')) return path
  const absolute = /^https?:\/\//.test(path)
  if (!path.startsWith('/') && !absolute) return path
  const url = new URL(path, origin)
  if (url.origin !== origin) return path
  if (!url.searchParams.has('dt_workspace'))
    url.searchParams.set('dt_workspace', url.searchParams.get('workspace') ?? workspaceId)
  return absolute ? url.toString() : `${url.pathname}${url.search}${url.hash}`
}

let navigate: ((path: string) => void) | undefined
let navigationVersion = 0

/** Installed by the root navigation bridge; callers need no router singleton. */
export function registerWorkspaceNavigator(push: (path: string) => void): () => void {
  navigate = push
  return () => { if (navigate === push) navigate = undefined }
}

export async function selectWorkspace(
  workspaceId: string,
  destination = '/learning',
  options?: { beforeNavigate?: () => Promise<void> }
): Promise<void> {
  const version = ++navigationVersion
  const pending: Promise<void>[] = []
  window.dispatchEvent(new CustomEvent('deeptutor:before-workspace-switch', { detail: pending }))
  try {
    await Promise.all(pending)
    if (version !== navigationVersion) return
    await options?.beforeNavigate?.()
  } catch {
    const { notify } = await import('./notifications')
    const { default: i18n } = await import('i18next')
    notify(i18n.t('Could not save the draft. Free browser storage before switching workspaces.'), { tone: 'error' })
    window.dispatchEvent(new CustomEvent('deeptutor:workspace-switch-error'))
    return
  }
  if (version !== navigationVersion) return
  // Next owns navigation. The workspace layout resets only scoped runtimes;
  // the document, account settings and loaded assets stay in place.
  const url = new URL(scopedUrl(destination, workspaceId), window.location.origin)
  navigate?.(`${url.pathname}${url.search}${url.hash}`)
}

/** Keep live runtimes when staying in one store; reset them before crossing stores. */
export function navigateTask(path: string, push: (path: string) => void): void {
  const url = new URL(path, window.location.origin)
  const target = workspaceIdOf(url.searchParams)
  if (target === null || target === activeWorkspaceId()) push(scopedUrl(path))
  else void selectWorkspace(target, path)
}

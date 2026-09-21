import { activeWorkspaceId, scopedUrl } from "@/lib/workspace-scope";

const inWorkspace = (path: string, id: string) => id ? scopedUrl(path, id) : path;

/** Canonical browser routes for personalized learning. Never use these for API requests. */
export const LEARNING_HUB = '/learning'
export const BOOKS_HOME = `${LEARNING_HUB}/books`
export const PRACTICE_HOME = `${LEARNING_HUB}/practice`
export const MASTERY_HOME = `${LEARNING_HUB}/mastery`
export const READING_HOME = `${LEARNING_HUB}/reading`
export const READING_MATERIALS = `${READING_HOME}/materials`
export const WATCHING_HOME = `${LEARNING_HUB}/watching`

const segment = (value: string) => encodeURIComponent(value.trim())

export function bookRoute(bookId?: string | null, pageId?: string | null, workspaceId = activeWorkspaceId()): string {
  if (!bookId?.trim()) return inWorkspace(BOOKS_HOME, workspaceId)
  const book = `${BOOKS_HOME}/${segment(bookId)}`
  return inWorkspace(pageId?.trim() ? `${book}/pages/${segment(pageId)}` : book, workspaceId)
}
export function masteryTopicRoute(pathId: string, workspaceId = activeWorkspaceId()): string {
  return inWorkspace(`${MASTERY_HOME}/${segment(pathId)}`, workspaceId)
}
export function masterySessionsRoute(pathId: string, query?: URLSearchParams, workspaceId = activeWorkspaceId()): string {
  const suffix = query?.toString()
  return inWorkspace(`${masteryTopicRoute(pathId, "")}/sessions${suffix ? `?${suffix}` : ''}`, workspaceId)
}
export function masterySessionRoute(pathId: string, sessionId: string, workspaceId = activeWorkspaceId()): string {
  return inWorkspace(`${masterySessionsRoute(pathId, undefined, "")}/${segment(sessionId)}`, workspaceId)
}
export function readingCollectionRoute(workspaceId: string, contentWorkspaceId = activeWorkspaceId()): string {
  return inWorkspace(`${READING_HOME}/${segment(workspaceId)}`, contentWorkspaceId)
}
export function readingSessionRoute(workspaceId: string, sessionId: string, contentWorkspaceId = activeWorkspaceId()): string {
  return inWorkspace(`${readingCollectionRoute(workspaceId, "")}/sessions/${segment(sessionId)}`, contentWorkspaceId)
}
export function watchingRoute(sessionId?: string | null, workspaceId = activeWorkspaceId()): string {
  return inWorkspace(sessionId?.trim() ? `${WATCHING_HOME}/${segment(sessionId)}` : WATCHING_HOME, workspaceId)
}
/** Follows native history binding as well as router navigation; rejects malformed URLs. */
export function readingSessionIdFromPath(pathname: string): string | null {
  const path = pathname.split(/[?#]/, 1)[0]
  if (!path.startsWith(`${READING_HOME}/`)) return null
  const parts = path.slice(READING_HOME.length + 1).split('/')
  if (!parts[0] || parts[1] !== 'sessions' || !parts[2] || parts.slice(3).some(Boolean)) return null
  try {
    return decodeURIComponent(parts[2]).trim() || null
  } catch {
    return null
  }
}

export function practiceRoute(query?: URLSearchParams, workspaceId = activeWorkspaceId()): string {
  const suffix = query?.toString();
  return inWorkspace(`${PRACTICE_HOME}${suffix ? `?${suffix}` : ""}`, workspaceId);
}

export function questionBankRoute(query?: URLSearchParams, workspaceId = activeWorkspaceId()): string {
  const suffix = query?.toString();
  return inWorkspace(`/space/questions${suffix ? `?${suffix}` : ""}`, workspaceId);
}

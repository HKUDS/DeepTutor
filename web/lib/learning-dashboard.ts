import { scopedUrl } from '@/lib/workspace-scope'
import type { Book } from '@/lib/book-types'
import type { MasteryTopic } from '@/lib/learning-api'
import type { ReadingWorkspace } from '@/lib/reading-workspace-api'
import type { SessionSummary } from '@/lib/session-api'
import {
  bookRoute,
  masteryTopicRoute,
  readingCollectionRoute,
  practiceRoute,
} from '@/lib/learning-routes'
import { bookPageOf, masteryPathIdOf, readingWorkspaceIdOf, sessionRoute } from '@/lib/mastery-session'
import { sessionWorkspaceId } from '@/lib/session-api'

export type LearningKind = 'books' | 'mastery' | 'reading' | 'watching' | 'practice'
export type Located<T> = T & { content_workspace_id?: string; content_workspace_name?: string }
export interface LearningSources {
  books: Located<Book>[]
  mastery: Located<MasteryTopic>[]
  reading: Located<ReadingWorkspace>[]
  practice?: Located<{ id: number; question: string; created_at: number; updated_at: number }>[]
  watching: SessionSummary[]
}
export interface LearningActivity {
  key: string
  kind: LearningKind
  title: string
  href: string
  updatedAt: number
  createdAt: number
  progress?: number
}
export function isWatchingSession(session: SessionSummary): boolean {
  return (
    session.preferences?.workspace_mode === 'immersive_watching' ||
    session.preferences?.capability === 'immersive_watching'
  )
}
/** Every activity across the surfaces, newest first. Archived paths are not work in progress. */
export function allLearningActivity(sources: LearningSources): LearningActivity[] {
  return [
    ...(sources.practice ?? []).map(entry => ({
      key: `practice:${entry.content_workspace_id || ''}:${entry.id}`,
      kind: 'practice' as const,
      title: entry.question,
      href: scopedUrl(
        practiceRoute(new URLSearchParams({ question: String(entry.id) }), ''),
        entry.content_workspace_id || ''
      ),
      updatedAt: entry.updated_at || entry.created_at,
      createdAt: entry.created_at || entry.updated_at,
    })),
    ...sources.books.map(book => ({
      key: `book:${book.content_workspace_id || ''}:${book.id}`,
      kind: 'books' as const,
      title: book.title,
      href: scopedUrl(bookRoute(book.id, null, ''), book.content_workspace_id || ''),
      updatedAt: book.updated_at,
      createdAt: book.created_at || book.updated_at,
      progress: (book.reading?.percent ?? 0) / 100,
    })),
    ...sources.mastery
      .filter(topic => topic.metadata.status === 'active')
      .map(topic => ({
        key: `topic:${topic.content_workspace_id || ''}:${topic.path_id}`,
        kind: 'mastery' as const,
        title: topic.name || topic.metadata.goal,
        href: scopedUrl(masteryTopicRoute(topic.path_id, ''), topic.content_workspace_id || ''),
        updatedAt: topic.updated_at,
        createdAt: topic.metadata.created_at || topic.updated_at,
        progress: topic.map.counts.total ? topic.map.counts.mastered / topic.map.counts.total : 0,
      })),
    ...sources.reading.map(workspace => ({
      key: `reading:${workspace.content_workspace_id || ''}:${workspace.workspace_id}`,
      kind: 'reading' as const,
      title: workspace.title,
      href: scopedUrl(
        readingCollectionRoute(workspace.workspace_id, ''),
        workspace.content_workspace_id || ''
      ),
      updatedAt: workspace.updated_at,
      createdAt: workspace.created_at || workspace.updated_at,
    })),
    ...sources.watching.filter(isWatchingSession).map(session => ({
      key: `session:${session.content_workspace_id || ''}:${session.session_id}`,
      kind: 'watching' as const,
      title: session.title,
      href: sessionRoute(session),
      updatedAt: session.updated_at,
      createdAt: session.created_at || session.updated_at,
    })),
  ].sort((a, b) => b.updatedAt - a.updatedAt || a.key.localeCompare(b.key))
}
/**
 * The learning record a conversation was held in — its path, collection or
 * book — keyed like ``allLearningActivity``, or null for one that names none.
 * The same links its route follows, so a conversation is filed exactly where
 * clicking it would take you.
 */
export function learningRecordKeyOf(session: SessionSummary): string | null {
  const workspace = sessionWorkspaceId(session)
  const pathId = masteryPathIdOf(session)
  if (pathId) return `topic:${workspace}:${pathId}`
  const collectionId = readingWorkspaceIdOf(session)
  if (collectionId) return `reading:${workspace}:${collectionId}`
  const book = bookPageOf(session)
  if (book) return `book:${workspace}:${book.bookId}`
  return null
}

/**
 * Learning conversations filed under the records they belong to. A
 * conversation whose record is not listed (an archived path, a deleted
 * collection) stands on its own rather than disappearing with it; one that
 * *is* a record (a legacy watching session) is not repeated.
 */
export function fileLearningSessions(records: readonly LearningActivity[], sessions: readonly SessionSummary[]) {
  const keys = new Set(records.map(record => record.key))
  const children = new Map<string, SessionSummary[]>()
  const loose: SessionSummary[] = []
  for (const session of sessions) {
    if (keys.has(`session:${sessionWorkspaceId(session)}:${session.session_id}`)) continue
    const key = learningRecordKeyOf(session)
    if (key && keys.has(key)) children.set(key, [...(children.get(key) ?? []), session])
    else loose.push(session)
  }
  return { children, loose }
}

export function recentLearningActivity(sources: LearningSources): LearningActivity[] {
  return allLearningActivity(sources).slice(0, 6)
}
/**
 * What each surface holds right now: how much, and the one piece of it the
 * learner touched last. The hub's surface cards lead with that title, so a
 * surface they already use names their own work rather than a bare count.
 */
export function learningSurfaceStats(
  sources: LearningSources
): Record<LearningKind, { count: number; latest?: LearningActivity }> {
  const stats: Record<LearningKind, { count: number; latest?: LearningActivity }> = {
    books: { count: 0 },
    mastery: { count: 0 },
    reading: { count: 0 },
    watching: { count: 0 },
    practice: { count: 0 },
  }
  // Sorted newest first, so the first activity seen for a kind is its latest.
  for (const activity of allLearningActivity(sources)) {
    const stat = stats[activity.kind]
    stat.count += 1
    stat.latest ??= activity
  }
  return stats
}
export function learningTodos(sources: LearningSources) {
  return {
    reviews: sources.mastery.filter(
      topic => topic.metadata.status === 'active' && topic.reviews.some(review => review.due)
    ),
    books: sources.books
      .filter(book => book.status === 'paused' || book.status === 'compiling')
      .sort(
        (a, b) =>
          Number(b.status === 'paused') - Number(a.status === 'paused') ||
          b.updated_at - a.updated_at
      ),
  }
}

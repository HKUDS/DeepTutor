import { scopedUrl } from "@/lib/workspace-scope";
import type { Book } from '@/lib/book-types'
import type { MasteryTopic } from '@/lib/learning-api'
import type { ReadingWorkspace } from '@/lib/reading-workspace-api'
import type { SessionSummary } from '@/lib/session-api'
import { bookRoute, masteryTopicRoute, readingCollectionRoute } from '@/lib/learning-routes'
import { sessionRoute } from '@/lib/mastery-session'

export type LearningKind = 'books' | 'mastery' | 'reading' | 'watching'
export type Located<T> = T & { content_workspace_id?: string; content_workspace_name?: string }
export interface LearningSources {
  books: Located<Book>[]
  mastery: Located<MasteryTopic>[]
  reading: Located<ReadingWorkspace>[]
  watching: SessionSummary[]
}
export interface LearningActivity {
  key: string
  kind: LearningKind
  title: string
  href: string
  updatedAt: number
  workspaceName?: string
  progress?: number
}
export function isWatchingSession(session: SessionSummary): boolean {
  return (
    session.preferences?.workspace_mode === 'immersive_watching' ||
    session.preferences?.capability === 'immersive_watching'
  )
}
/** Every activity across the surfaces, newest first. Archived paths are not work in progress. */
function allLearningActivity(sources: LearningSources): LearningActivity[] {
  return [
    ...sources.books.map(book => ({
      key: `book:${book.content_workspace_id || ""}:${book.id}`,
      kind: 'books' as const,
      title: book.title,
      href: scopedUrl(bookRoute(book.id, null, ""), book.content_workspace_id || ""),
      updatedAt: book.updated_at,
      workspaceName: book.content_workspace_name,
      progress: (book.reading?.percent ?? 0) / 100,
    })),
    ...sources.mastery
      .filter(topic => topic.metadata.status === 'active')
      .map(topic => ({
        key: `topic:${topic.content_workspace_id || ""}:${topic.path_id}`,
        kind: 'mastery' as const,
        title: topic.name || topic.metadata.goal,
        href: scopedUrl(masteryTopicRoute(topic.path_id, ""), topic.content_workspace_id || ""),
        updatedAt: topic.updated_at,
        workspaceName: topic.content_workspace_name,
        progress: topic.map.counts.total ? topic.map.counts.mastered / topic.map.counts.total : 0,
      })),
    ...sources.reading.map(workspace => ({
      key: `reading:${workspace.content_workspace_id || ""}:${workspace.workspace_id}`,
      kind: 'reading' as const,
      title: workspace.title,
      href: scopedUrl(readingCollectionRoute(workspace.workspace_id, ""), workspace.content_workspace_id || ""),
      updatedAt: workspace.updated_at,
      workspaceName: workspace.content_workspace_name,
    })),
    ...sources.watching.filter(isWatchingSession).map(session => ({
      key: `session:${session.session_id}`,
      kind: 'watching' as const,
      title: session.title,
      href: sessionRoute(session),
      updatedAt: session.updated_at,
    })),
  ].sort((a, b) => b.updatedAt - a.updatedAt || a.key.localeCompare(b.key))
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

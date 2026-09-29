import { listCourses, type StudyCourse } from '@/lib/courses-api'
import { fetchMasteryTopicIndex, type MasteryTopicLabel } from '@/lib/learning-api'
import {
  fetchReadingCollectionIndex,
  type ReadingCollectionLabel,
} from '@/lib/reading-workspace-api'
import { listSessions, type SessionSummary } from '@/lib/session-api'

export interface SidebarSummaries {
  sessions: SessionSummary[]
  courses: StudyCourse[]
  masteryTopics: MasteryTopicLabel[]
  readingCollections: ReadingCollectionLabel[]
}

interface SummaryLoaders {
  listSessions?: () => Promise<SessionSummary[]>
  listCourses?: typeof listCourses
  fetchMasteryTopicIndex?: typeof fetchMasteryTopicIndex
  fetchReadingCollectionIndex?: typeof fetchReadingCollectionIndex
}

export async function loadSidebarSummaries(
  loaders: SummaryLoaders = {},
): Promise<SidebarSummaries> {
  const resolved = {
    listSessions: () => listSessions(50, 0, { force: true }),
    listCourses,
    fetchMasteryTopicIndex,
    fetchReadingCollectionIndex,
    ...loaders,
  }
  const [sessions, courses, masteryTopics, readingCollections] = await Promise.all([
    resolved.listSessions(),
    resolved.listCourses({ force: true }).catch(() => [] as StudyCourse[]),
    resolved.fetchMasteryTopicIndex().catch(() => [] as MasteryTopicLabel[]),
    resolved.fetchReadingCollectionIndex().catch(() => [] as ReadingCollectionLabel[]),
  ])
  return { sessions, courses, masteryTopics, readingCollections }
}

import { listCourses, type StudyCourse } from "@/lib/courses-api";
import {
  fetchMasteryTopicIndex,
  type MasteryTopicLabel,
} from "@/lib/learning-api";
import {
  fetchReadingCollectionIndex,
  type ReadingCollectionLabel,
} from "@/lib/reading-workspace-api";
import { listSessions, type SessionSummary } from "@/lib/session-api";

export interface SidebarSummaries {
  sessions: SessionSummary[];
  courses: StudyCourse[];
  masteryTopics: MasteryTopicLabel[];
  readingCollections: ReadingCollectionLabel[];
}

interface SummaryLoaders {
  listSessions: typeof listSessions;
  listCourses: typeof listCourses;
  fetchMasteryTopicIndex: typeof fetchMasteryTopicIndex;
  fetchReadingCollectionIndex: typeof fetchReadingCollectionIndex;
}

export async function loadSidebarSummaries(
  loaders: SummaryLoaders = {
    listSessions,
    listCourses,
    fetchMasteryTopicIndex,
    fetchReadingCollectionIndex,
  },
): Promise<SidebarSummaries> {
  const [sessions, courses, masteryTopics, readingCollections] =
    await Promise.all([
      loaders.listSessions(50, 0, { force: true }),
      loaders.listCourses({ force: true }).catch(() => [] as StudyCourse[]),
      loaders.fetchMasteryTopicIndex().catch(() => [] as MasteryTopicLabel[]),
      loaders
        .fetchReadingCollectionIndex()
        .catch(() => [] as ReadingCollectionLabel[]),
    ]);
  return { sessions, courses, masteryTopics, readingCollections };
}

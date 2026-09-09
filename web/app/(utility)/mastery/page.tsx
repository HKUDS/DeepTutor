"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  CourseScopeChip,
  useCourseScope,
} from "@/components/courses/CourseScope";
import { CreateTopicWizard } from "@/components/space/learning/CreateTopicWizard";
import type { Translate } from "@/components/space/learning/format";
import { topicDisplayName } from "@/components/space/learning/format";
import { StartFromBookDialog } from "@/components/space/learning/StartFromBookDialog";
import { TopicAtlas } from "@/components/space/learning/TopicAtlas";
import { bookApi } from "@/lib/book-api";
import {
  fetchAllProgress,
  fetchMasteryTopics,
  type MasteryTopic,
  type ProgressSummary,
} from "@/lib/learning-api";
import {
  MASTERY_OPENING_SCOPE,
  masteryOpeningMessage,
  masterySessionRoute,
} from "@/lib/mastery-mode";
import { setPendingPrompt } from "@/lib/pending-prompt";

function MasteryPathRoute() {
  const router = useRouter();
  const { t } = useTranslation();
  const [topics, setTopics] = useState<MasteryTopic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const wizardTriggerRef = useRef<HTMLElement | null>(null);
  // path_id → current_stage. The topic payload does not carry the stage; the
  // progress summaries do, and the cards use it for the diagnostic hand-off.
  const [stages, setStages] = useState<Record<string, string>>({});
  // Progress summaries not covered by a topic card: book-type paths, which
  // started straight from a parsed textbook and have no goal conversation.
  const [bookPaths, setBookPaths] = useState<ProgressSummary[]>([]);
  // Whether the bookshelf has anything to offer the empty state's
  // "start from your textbook" entry. Null = not probed yet.
  const [hasBooks, setHasBooks] = useState<boolean | null>(null);
  const [startDialogOpen, setStartDialogOpen] = useState(false);
  const startTriggerRef = useRef<HTMLElement | null>(null);
  // Present when opened from a course page or a Course Study hand-off. It both
  // narrows the atlas to that course's paths and adopts whatever is built here.
  const scope = useCourseScope();

  const loadTopics = useCallback(async () => {
    setError(null);
    try {
      setTopics(await fetchMasteryTopics({ cache: "no-store" }));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("The atlas could not be loaded."),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  const loadStages = useCallback(async () => {
    try {
      const { summaries } = await fetchAllProgress();
      setStages(
        Object.fromEntries(
          summaries.map((summary) => [summary.book_id, summary.current_stage]),
        ),
      );
      setBookPaths(summaries);
    } catch {
      // Stage hints are progressive enhancement — the atlas renders without
      // them when the summaries endpoint is unavailable.
    }
  }, []);

  // The bookshelf is only probed when the atlas looks empty: the
  // "start from your textbook" entry has nothing to offer otherwise.
  const probeBooks = useCallback(async () => {
    if (hasBooks !== null) return;
    try {
      const { books } = await bookApi.list();
      setHasBooks(books.length > 0);
    } catch {
      setHasBooks(false);
    }
  }, [hasBooks]);

  useEffect(() => {
    void loadTopics();
    void loadStages();
  }, [loadTopics, loadStages]);

  // A topic list that stays empty (not still loading) is the signal to check
  // the bookshelf for the empty state's textbook entry.
  useEffect(() => {
    if (!loading && topics.length === 0) void probeBooks();
  }, [loading, topics.length, probeBooks]);

  const handleTopicDeleted = useCallback((pathId: string) => {
    setTopics((previous) =>
      previous.filter((topic) => topic.path_id !== pathId),
    );
    setStages((previous) => {
      const next = { ...previous };
      delete next[pathId];
      return next;
    });
    setBookPaths((previous) =>
      previous.filter((summary) => summary.book_id !== pathId),
    );
  }, []);

  const handleTopicImported = useCallback(
    (_pathId: string, _moduleCount: number) => {
      // The import filled the route server-side; reload so the card drops its
      // empty-topic guidance and shows the real map.
      setLoading(true);
      void loadTopics();
      void loadStages();
    },
    [loadTopics, loadStages],
  );

  const handleBookStarted = useCallback(
    (_bookId: string, _moduleCount: number) => {
      // The one-click import built the path server-side; reload the atlas so
      // the book's card appears in the textbook-progress group.
      setStartDialogOpen(false);
      setLoading(true);
      void loadTopics();
      void loadStages();
    },
    [loadTopics, loadStages],
  );

  // A course that references no path yet scopes the atlas to nothing, and the
  // empty state then invites building the first one — which is the move that
  // was previously a dead end. Summaries without a topic card are book-type
  // paths; the same scope rule applies to them.
  const scopedTopics = useMemo(() => {
    if (!scope) return topics;
    const allowed = new Set(scope.refIds("mastery_path"));
    return topics.filter((topic) => allowed.has(topic.path_id));
  }, [scope, topics]);
  const scopedBookPaths = useMemo(() => {
    if (!scope) return bookPaths;
    const allowed = new Set(scope.refIds("mastery_path"));
    return bookPaths.filter((summary) => allowed.has(summary.book_id));
  }, [scope, bookPaths]);

  return (
    <>
      <TopicAtlas
        topics={scopedTopics}
        loading={loading}
        error={error}
        scopeChip={scope ? <CourseScopeChip scope={scope} /> : null}
        stages={stages}
        onTopicDeleted={handleTopicDeleted}
        onTopicImported={handleTopicImported}
        bookPaths={scopedBookPaths.filter(
          (summary) => !scopedTopics.some((topic) => topic.path_id === summary.book_id),
        )}
        canStartFromBook={hasBooks === true}
        onStartFromBook={(trigger) => {
          startTriggerRef.current = trigger;
          setStartDialogOpen(true);
        }}
        onCreate={(trigger) => {
          wizardTriggerRef.current = trigger;
          setWizardOpen(true);
        }}
        onRetry={() => {
          setLoading(true);
          void loadTopics();
          void loadStages();
        }}
      />
      {startDialogOpen && (
        <StartFromBookDialog
          returnFocusRef={startTriggerRef}
          onClose={() => setStartDialogOpen(false)}
          onStarted={handleBookStarted}
        />
      )}
      {wizardOpen && (
        <CreateTopicWizard
          returnFocusRef={wizardTriggerRef}
          onClose={() => setWizardOpen(false)}
          onCreated={async (topic) => {
            setWizardOpen(false);
            await scope?.attach(
              "mastery_path",
              topic.path_id,
              topicDisplayName(topic, t as Translate),
            );
            // Straight into the goal's outline session: a goal is created
            // without an outline, and that kind of session is the one that
            // designs it — it cannot examine the learner, and it opens by
            // reading their materials rather than waiting to be prompted.
            // The button they pressed is the request; the conversation opens
            // by sending it rather than by asking them to phrase it again.
            setPendingPrompt(
              masteryOpeningMessage("outline", t),
              MASTERY_OPENING_SCOPE,
            );
            router.push(masterySessionRoute(topic.path_id, "outline"));
          }}
        />
      )}
    </>
  );
}

export default function MasteryPathPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      }
    >
      <MasteryPathRoute />
    </Suspense>
  );
}

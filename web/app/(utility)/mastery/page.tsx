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
import { TopicAtlas } from "@/components/space/learning/TopicAtlas";
import { fetchMasteryTopics, type MasteryTopic } from "@/lib/learning-api";
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

  useEffect(() => {
    void loadTopics();
  }, [loadTopics]);

  // A course that references no path yet scopes the atlas to nothing, and the
  // empty state then invites building the first one — which is the move that
  // was previously a dead end.
  const scopedTopics = useMemo(() => {
    if (!scope) return topics;
    const allowed = new Set(scope.refIds("mastery_path"));
    return topics.filter((topic) => allowed.has(topic.path_id));
  }, [scope, topics]);

  return (
    <>
      <TopicAtlas
        topics={scopedTopics}
        loading={loading}
        error={error}
        scopeChip={scope ? <CourseScopeChip scope={scope} /> : null}
        onCreate={(trigger) => {
          wizardTriggerRef.current = trigger;
          setWizardOpen(true);
        }}
        onRetry={() => {
          setLoading(true);
          void loadTopics();
        }}
      />
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

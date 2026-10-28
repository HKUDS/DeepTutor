"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CreateTopicWizard } from "@/components/space/learning/CreateTopicWizard";
import { TopicAtlas } from "@/components/space/learning/TopicAtlas";
import { learningLibrary } from "@/lib/learning-library";
import { useCreateRequest, requestedLearningCreation } from "@/components/learning/create-request";
import { type MasteryTopic } from "@/lib/learning-api";
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
  const [wizardOpen, setWizardOpen] = useState(requestedLearningCreation);
  const wizardTriggerRef = useRef<HTMLElement | null>(null);
  useCreateRequest(() => setWizardOpen(true));

  const loadTopics = useCallback(async () => {
    setError(null);
    try {
      const result = await learningLibrary<MasteryTopic>("mastery");
      setTopics(result.items);
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


  return (
    <>
      <TopicAtlas
        topics={topics}
        loading={loading}
        error={error}
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

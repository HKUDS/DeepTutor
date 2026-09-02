"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useChatStateAdapter,
  type SessionConfiguration,
} from "@/features/chat/ChatStateAdapter";
import { useMasteryPathActivity } from "@/hooks/useMasteryPathActivity";
import {
  fetchMasteryTopic,
  fetchMasteryTopicSessions,
  type MasteryTopic,
} from "@/lib/learning-api";
import {
  isMasteryDraftSessionReady,
  type MasteryDraftRouteGuard,
} from "@/lib/mastery-study-route";
import { courseSessionConfiguration } from "@/lib/course-session-scope";
import { MASTERY_WORKSPACE_MODE } from "@/lib/workspace-mode";

/**
 * Resolves which topic and which chat session a study route is showing.
 *
 * Route → session is a small state machine: a bare `/sessions` route opens a
 * draft and rewrites the URL once the session exists, while a route that
 * names a session must first prove that session belongs to this topic. Both
 * paths key their bookkeeping on the route so a fast topic switch can never
 * apply a stale answer to the wrong screen.
 */
export function useMasteryStudySession(
  pathId: string,
  routeSessionId?: string,
  courseId = "",
) {
  const router = useRouter();
  const { t } = useTranslation();
  const {
    state,
    newSession,
    configureSession,
    loadSession,
    showCachedSession,
  } = useChatStateAdapter();

  const [topic, setTopic] = useState<MasteryTopic | null>(null);
  const [topicError, setTopicError] = useState<string | null>(null);
  const currentRouteKey = `${pathId}:${routeSessionId || "new"}`;
  const [sessionResolution, setSessionResolution] = useState<{
    routeKey: string;
    error: string | null;
  } | null>(null);
  const initializedRouteRef = useRef("");
  const draftRouteGuardRef = useRef<MasteryDraftRouteGuard | null>(null);
  const activity = useMasteryPathActivity(pathId || null);

  useEffect(() => {
    let active = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the route-owned request state before fetching.
    setTopicError(null);
    void fetchMasteryTopic(pathId, { cache: "no-store" })
      .then((result) => {
        if (active) setTopic(result);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setTopicError(
          reason instanceof Error
            ? reason.message
            : t("The learning map could not be loaded"),
        );
      });
    return () => {
      active = false;
    };
  }, [activity.revision, pathId, t]);

  const knowledgeBases = useMemo(
    () =>
      topic?.sources
        .filter(
          (source) =>
            source.kind === "knowledge_base" &&
            source.available &&
            source.source_id,
        )
        .map((source) => source.source_id) ?? [],
    [topic],
  );
  const sessionConfiguration = useMemo<SessionConfiguration>(
    () => ({
      workspaceMode: MASTERY_WORKSPACE_MODE,
      capability: null,
      masteryPathId: pathId,
      knowledgeBases,
    }),
    [knowledgeBases, pathId],
  );

  useEffect(() => {
    if (!topic) return;
    const routeKey = currentRouteKey;
    if (initializedRouteRef.current === routeKey) return;
    initializedRouteRef.current = routeKey;

    if (!routeSessionId) {
      draftRouteGuardRef.current = {
        routeKey,
        previousSessionId: state.sessionId,
      };
      newSession(courseSessionConfiguration(sessionConfiguration, courseId));
      return;
    }

    draftRouteGuardRef.current = null;

    void fetchMasteryTopicSessions(pathId, { cache: "no-store" })
      .then((topicSessions) => {
        if (
          !topicSessions.some(
            (candidate) => candidate.session_id === routeSessionId,
          )
        ) {
          throw new Error(
            t(
              "This session belongs to a different topic. Open a session from this topic instead.",
            ),
          );
        }
        const cached = showCachedSession(routeSessionId);
        if (cached) {
          configureSession(
            courseSessionConfiguration(sessionConfiguration, courseId),
            routeSessionId,
          );
        }
        return loadSession(
          routeSessionId,
          cached ? { revalidate: true } : undefined,
        );
      })
      .then(() => {
        configureSession(
          courseSessionConfiguration(sessionConfiguration, courseId),
          routeSessionId,
        );
        setSessionResolution({ routeKey, error: null });
      })
      .catch((reason: unknown) => {
        setSessionResolution({
          routeKey,
          error:
            reason instanceof Error
              ? reason.message
              : t("This learning session could not be opened"),
        });
      });
  }, [
    courseId,
    configureSession,
    currentRouteKey,
    loadSession,
    newSession,
    pathId,
    routeSessionId,
    sessionConfiguration,
    showCachedSession,
    state.sessionId,
    t,
    topic,
  ]);

  useEffect(() => {
    const newSessionId = state.sessionId;
    if (
      routeSessionId ||
      !newSessionId ||
      !isMasteryDraftSessionReady({
        guard: draftRouteGuardRef.current,
        routeKey: currentRouteKey,
        sessionId: newSessionId,
        masteryPathId: state.masteryPathId,
        pathId,
      })
    )
      return;
    const courseQuery = courseId
      ? `?course=${encodeURIComponent(courseId)}`
      : "";
    router.replace(
      `/mastery/${encodeURIComponent(pathId)}/sessions/${encodeURIComponent(
        newSessionId,
      )}${courseQuery}`,
      { scroll: false },
    );
  }, [
    currentRouteKey,
    courseId,
    pathId,
    routeSessionId,
    router,
    state.masteryPathId,
    state.sessionId,
  ]);

  const sessionError =
    sessionResolution?.routeKey === currentRouteKey
      ? sessionResolution.error
      : null;
  const sessionLoading = Boolean(
    routeSessionId && sessionResolution?.routeKey !== currentRouteKey,
  );

  return { topic, topicError, knowledgeBases, sessionError, sessionLoading };
}

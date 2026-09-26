"use client";

import { navigateTask } from "@/lib/workspace-scope";
import { sessionWorkspaceId } from "@/lib/session-api";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { SidebarShell } from "@/components/sidebar/SidebarShell";
import { LogoutButton } from "@/components/auth/LogoutButton";
import { AdminLink } from "@/components/auth/AdminLink";
import { ProfileLink } from "@/components/auth/ProfileLink";
import { useAppShell } from "@/context/AppShellContext";
import {
  deleteSession,
  listSessions,
  updateSessionOrganization,
  updateSessionTitle,
  type SessionOrganizationPatch,
  type SessionSummary,
} from "@/lib/session-api";
import { listCourses, type StudyCourse } from "@/lib/courses-api";
import {
  fetchReadingCollectionIndex,
  type ReadingCollectionLabel,
} from "@/lib/reading-workspace-api";
import {
  fetchMasteryTopicIndex,
  type MasteryTopicLabel,
} from "@/lib/learning-api";
import { sessionRoute } from "@/lib/mastery-session";
import { subscribeSessionChanges } from "@/lib/session-events";

export default function UtilitySidebar() {
  const { t } = useTranslation();
  const router = useRouter();
  const { activeSessionId, setActiveSessionId } = useAppShell();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [courses, setCourses] = useState<StudyCourse[]>([]);
  const [masteryTopics, setMasteryTopics] = useState<MasteryTopicLabel[]>([]);
  const [readingCollections, setReadingCollections] = useState<
    ReadingCollectionLabel[]
  >([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const hasLoadedSessionsRef = useRef(false);

  const refreshSessions = useCallback(async () => {
    if (!hasLoadedSessionsRef.current) {
      setLoadingSessions(true);
    }
    try {
      // Labels only name a heading, so losing them costs grouping, not the list.
      const [nextSessions, nextCourses, nextTopics, nextCollections] =
        await Promise.all([
          listSessions(50, 0, { force: true, allWorkspaces: true }),
          listCourses({ force: true }).catch(() => [] as StudyCourse[]),
          fetchMasteryTopicIndex().catch(() => [] as MasteryTopicLabel[]),
          fetchReadingCollectionIndex().catch(() => [] as ReadingCollectionLabel[]),
        ]);
      setSessions(nextSessions);
      setCourses(nextCourses);
      setMasteryTopics(nextTopics);
      setReadingCollections(nextCollections);
      hasLoadedSessionsRef.current = true;
    } catch (error) {
      console.error("Failed to load sessions", error);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  // A conversation can be archived, restored or deleted from a route the
  // sidebar knows nothing about — Settings › Archive being the reason this
  // exists. Without it the list keeps hiding a conversation that was just
  // restored two panes away.
  useEffect(
    () => subscribeSessionChanges(() => void refreshSessions()),
    [refreshSessions],
  );

  // A study conversation opens on its own path — see ``sessionRoute``.
  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      setActiveSessionId(sessionId);
      const session = sessions.find((item) => item.session_id === sessionId);
      navigateTask(session ? sessionRoute(session) : `/chat/${sessionId}`, router.push);
    },
    [router, sessions, setActiveSessionId],
  );

  const handleRenameSession = useCallback(
    async (sessionId: string, title: string) => {
      const updated = await updateSessionTitle(sessionId, title, sessionWorkspaceId(sessions.find(item => item.session_id === sessionId)));
      setSessions((prev) =>
        prev.map((session) =>
          session.session_id === sessionId
            ? {
                ...session,
                title: updated.title,
                updated_at: updated.updated_at,
              }
            : session,
        ),
      );
    },
    [sessions],
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Permanently delete this chat and its tutor threads? This cannot be undone."))) return;
      await deleteSession(sessionId, sessionWorkspaceId(sessions.find(item => item.session_id === sessionId)));
      setSessions((prev) =>
        prev.filter((session) => session.session_id !== sessionId),
      );
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
      }
    },
    [activeSessionId, setActiveSessionId, t, sessions],
  );

  const handleOrganizeSession = useCallback(
    async (sessionId: string, patch: SessionOrganizationPatch) => {
      const updated = await updateSessionOrganization(sessionId, patch, sessionWorkspaceId(sessions.find(item => item.session_id === sessionId)));
      setSessions((previous) =>
        previous.map((session) =>
          session.session_id === sessionId
            ? {
                ...session,
                updated_at: updated.updated_at,
                preferences: updated.preferences,
                content_workspace_id: "workspace_id" in patch ? updated.preferences?.workspace_id || "" : session.content_workspace_id,
              }
            : session,
        ),
      );
    },
    [sessions],
  );

  return (
    <SidebarShell
      showSessions
      sessions={sessions}
      courses={courses}
      masteryTopics={masteryTopics}
      readingCollections={readingCollections}
      activeSessionId={activeSessionId}
      loadingSessions={loadingSessions}
      onNewChat={() => setActiveSessionId(null)}
      onSelectSession={handleSelectSession}
      onRenameSession={handleRenameSession}
      onDeleteSession={handleDeleteSession}
      onOrganizeSession={handleOrganizeSession}
      footerSlot={(collapsed) => (
        <>
          <ProfileLink collapsed={collapsed} />
          <AdminLink collapsed={collapsed} />
          <LogoutButton collapsed={collapsed} />
        </>
      )}
    />
  );
}

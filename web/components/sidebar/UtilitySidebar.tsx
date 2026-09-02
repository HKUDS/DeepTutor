"use client";

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
          listSessions(50, 0, { force: true }),
          listCourses({ force: true }),
          fetchMasteryTopicIndex().catch(() => [] as MasteryTopicLabel[]),
          fetchReadingCollectionIndex(),
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

  // A study conversation opens on its own path — see ``sessionRoute``.
  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      setActiveSessionId(sessionId);
      const session = sessions.find((item) => item.session_id === sessionId);
      router.push(session ? sessionRoute(session) : `/chat/${sessionId}`);
    },
    [router, sessions, setActiveSessionId],
  );

  const handleRenameSession = useCallback(
    async (sessionId: string, title: string) => {
      const updated = await updateSessionTitle(sessionId, title);
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
    [],
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Delete this chat history?"))) return;
      await deleteSession(sessionId);
      setSessions((prev) =>
        prev.filter((session) => session.session_id !== sessionId),
      );
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
      }
    },
    [activeSessionId, setActiveSessionId, t],
  );

  const handleOrganizeSession = useCallback(
    async (sessionId: string, patch: SessionOrganizationPatch) => {
      const updated = await updateSessionOrganization(sessionId, patch);
      setSessions((previous) =>
        previous.map((session) =>
          session.session_id === sessionId
            ? {
                ...session,
                updated_at: updated.updated_at,
                preferences: updated.preferences,
              }
            : session,
        ),
      );
    },
    [],
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

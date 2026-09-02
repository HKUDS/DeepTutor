"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { SidebarShell } from "@/components/sidebar/SidebarShell";
import { LogoutButton } from "@/components/auth/LogoutButton";
import { AdminLink } from "@/components/auth/AdminLink";
import { ProfileLink } from "@/components/auth/ProfileLink";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
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

export default function WorkspaceSidebar() {
  const { t } = useTranslation();
  const router = useRouter();
  const {
    newSession,
    cancelStreamingTurn,
    selectedSessionId,
    sessionStatuses,
    sidebarRefreshToken,
  } = useChatStateAdapter();
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
      // Topic labels are only there to name a group heading, so a failure to
      // load them must not cost the session list: the conversations then read
      // as ungrouped rather than as missing.
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

  // First mount shows the skeleton; subsequent refreshes triggered by
  // ``sidebarRefreshToken`` (STREAM_END, server-side session bind,
  // turn deletion) silently swap in the new list. Resetting the ref
  // each refresh briefly re-renders the loading skeleton, which the
  // user perceives as a flicker on every message send / Answer Now.
  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions, sidebarRefreshToken]);

  const orderedSessions = sessions
    .map((session, index) => {
      const runtime = sessionStatuses[session.session_id];
      return {
        index,
        session: runtime
          ? {
              ...session,
              status: runtime.status,
              active_turn_id: runtime.activeTurnId || session.active_turn_id,
            }
          : session,
      };
    })
    .sort((a, b) => {
      const aPriority = a.session.status === "running" ? 0 : 1;
      const bPriority = b.session.status === "running" ? 0 : 1;
      if (aPriority !== bPriority) return aPriority - bPriority;
      return a.index - b.index;
    })
    .map(({ session }) => session);

  // Cancel any in-flight streaming turn before starting a fresh session, so a
  // new chat never inherits a still-running turn (mirrors handleDeleteSession).
  const handleNewChat = useCallback(() => {
    cancelStreamingTurn();
    newSession();
    router.push("/chat");
  }, [cancelStreamingTurn, newSession, router]);

  // A study conversation opens on its own path, not in the main chat: the
  // outline, the waypoint header and the tutor's own composer are the context
  // it was held in, and /chat would drop all three.
  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      const session = sessions.find((item) => item.session_id === sessionId);
      router.push(session ? sessionRoute(session) : `/chat/${sessionId}`);
    },
    [router, sessions],
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
      if (selectedSessionId === sessionId) {
        cancelStreamingTurn();
        newSession();
        router.push("/chat");
      }
    },
    [cancelStreamingTurn, newSession, router, selectedSessionId, t],
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
      sessions={orderedSessions}
      courses={courses}
      masteryTopics={masteryTopics}
      readingCollections={readingCollections}
      activeSessionId={selectedSessionId}
      loadingSessions={loadingSessions}
      onNewChat={handleNewChat}
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

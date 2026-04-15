"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { SidebarShell } from "@/components/sidebar/SidebarShell";
import { useUnifiedChat } from "@/context/UnifiedChatContext";
import {
  deleteSession,
  listSessions,
  updateSessionTitle,
  type SessionSummary,
} from "@/lib/session-api";

export default function WorkspaceSidebar() {
  const { t } = useTranslation();
  const router = useRouter();
  const { newSession, selectedSessionId, sessionStatuses, sidebarRefreshToken } =
    useUnifiedChat();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const hasLoadedSessionsRef = useRef(false);

  const refreshSessions = useCallback(async () => {
    if (!hasLoadedSessionsRef.current) {
      setLoadingSessions(true);
    }
    try {
      setSessions(await listSessions(50, 0, { force: true }));
      hasLoadedSessionsRef.current = true;
    } catch (error) {
      console.error("Failed to load sessions", error);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

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

  const handleNewChat = () => {
    newSession();
    router.push("/chat");
  };

  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      router.push(`/chat/${sessionId}`);
    },
    [router],
  );

  const handleRenameSession = useCallback(async (sessionId: string, title: string) => {
    const updated = await updateSessionTitle(sessionId, title);
    setSessions((prev) =>
      prev.map((session) =>
        session.session_id === sessionId
          ? { ...session, title: updated.title, updated_at: updated.updated_at }
          : session,
      ),
    );
  }, []);

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Delete this chat history?"))) return;
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((session) => session.session_id !== sessionId));
      if (selectedSessionId === sessionId) {
        newSession();
        router.push("/chat");
      }
    },
    [newSession, router, selectedSessionId, t],
  );

  return (
    <SidebarShell
      showSessions
      sessions={orderedSessions}
      activeSessionId={selectedSessionId}
      loadingSessions={loadingSessions}
      onNewChat={handleNewChat}
      onSelectSession={handleSelectSession}
      onRenameSession={handleRenameSession}
      onDeleteSession={handleDeleteSession}
    />
  );
}

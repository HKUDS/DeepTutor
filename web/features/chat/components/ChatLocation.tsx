"use client";

import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { InstanceCrumb, type CrumbItem } from "@/components/layout/LocationCrumbs";
import { isLearningSession } from "@/lib/navigation";
import { sessionRoute } from "@/lib/mastery-session";
import { listSessions, searchSessions, type SessionSummary } from "@/lib/session-api";
import { displaySessionTitle } from "@/lib/session-title";

const listed = (session: SessionSummary) =>
  !session.preferences?.archived &&
  !session.preferences?.parent_session_id &&
  !isLearningSession(session);

/**
 * 「聊天 / this conversation」: the conversation as the page bar's instance
 * crumb. It opens onto the conversations the sidebar lists — same filter:
 * no archived ones, no tutor side threads, no learning sessions (those live
 * under their study record) — with a new chat on top and the full history
 * at the bottom.
 */
export function ChatLocation({
  sessionId,
  title,
  placeholder,
  onRename,
  onNewChat,
}: {
  sessionId: string | null;
  title: string;
  /** A draft with no conversation yet: nothing to rename. */
  placeholder: boolean;
  onRename?: () => void;
  onNewChat: () => void;
}) {
  const { t } = useTranslation();
  const toItem = useCallback(
    (session: SessionSummary): CrumbItem => ({
      id: session.session_id,
      label: displaySessionTitle(session.title, t("New conversation")),
      href: sessionRoute(session),
      updatedAt: session.updated_at,
    }),
    [t],
  );
  const load = useCallback(
    async () => (await listSessions(60)).filter(listed).map(toItem),
    [toItem],
  );
  const search = useCallback(
    async (query: string, signal: AbortSignal) =>
      (await searchSessions(query, 40, 0, signal)).sessions.filter(listed).map(toItem),
    [toItem],
  );
  return (
    <InstanceCrumb
      label={title}
      placeholder={placeholder}
      menuLabel={t("Recent conversations")}
      currentId={sessionId}
      load={load}
      search={search}
      create={{ label: t("New chat"), onSelect: onNewChat }}
      all={{ label: t("All conversations"), href: "/space/chat-history" }}
      onRename={onRename}
    />
  );
}

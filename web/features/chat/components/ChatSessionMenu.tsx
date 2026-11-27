"use client";

/**
 * ChatSessionMenu — the chat header's "⋯": the open conversation's own
 * actions. The items are the ones its sidebar row offers
 * (``SessionActionsMenuItems``), so the conversation reads the same from
 * either side, plus what only the open conversation can do — save it to a
 * notebook, export it as Markdown — moved here off the header itself.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BookmarkPlus, Download, MoreHorizontal, Unlink } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SESSION_MENU_SURFACE,
  SESSION_MENU_WIDTH,
  SessionActionsMenuItems,
  SessionMenuDivider,
  SessionMenuItem,
} from "@/components/sessions/SessionActionsMenu";
import HeaderActionButton from "@/features/chat/components/HeaderActionButton";
import { placeMenuBelow, type FloatingMenuPosition } from "@/lib/floating-menu";
import { notify } from "@/lib/notifications";
import {
  deleteSession,
  updateSessionOrganization,
  type SessionDetail,
  type SessionOrganizationPatch,
} from "@/lib/session-api";
import type { SessionOrganization } from "@/hooks/useSessionOrganization";
import { sessionTaskLinks, setTaskStatusLink } from "@/lib/task-board-api";
import { useTaskBoard } from "@/lib/task-board-store";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";

interface ChatSessionMenuProps {
  /** Null for a draft: nothing to organize until the first turn. */
  sessionId: string | null;
  /** The store this conversation lives in ("" = general). */
  workspaceId: string;
  /** Its organization as last read; null before the first read lands. */
  row: SessionOrganization | null;
  title: string;
  workspaces: ChatWorkspaceRegistration[];
  /** A turn is streaming. */
  live: boolean;
  canSave: boolean;
  onSave: () => void;
  canExport: boolean;
  onExport: () => void;
  /** Start editing the title in place. */
  onRename: () => void;
  onOrganized: (row: SessionOrganization) => void;
  /** It now lives in another workspace; the page should follow it there. */
  onMoved: (row: SessionDetail) => void;
  onDeleted: () => void;
}

export default function ChatSessionMenu({
  sessionId,
  workspaceId,
  row,
  title,
  workspaces,
  live,
  canSave,
  onSave,
  canExport,
  onExport,
  onRename,
  onOrganized,
  onMoved,
  onDeleted,
}: ChatSessionMenuProps) {
  const { t } = useTranslation();
  const { board: taskBoard } = useTaskBoard();
  const anchorRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<FloatingMenuPosition | null>(null);
  const [moving, setMoving] = useState(false);
  const open = position !== null;

  const close = useCallback(() => setPosition(null), []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (menuRef.current?.contains(target) || anchorRef.current?.contains(target)) {
        return;
      }
      close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // The viewer panel also closes on Escape; this press was the menu's.
      event.stopPropagation();
      close();
      anchorRef.current?.focus();
    };
    const onScroll = (event: Event) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) {
        return;
      }
      close();
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [close, open]);

  // A different conversation is a different menu.
  const [menuSessionId, setMenuSessionId] = useState(sessionId);
  if (menuSessionId !== sessionId) {
    setMenuSessionId(sessionId);
    setPosition(null);
  }

  const toggle = () => {
    if (open) {
      close();
      return;
    }
    const anchor = anchorRef.current;
    if (!anchor) return;
    setPosition(placeMenuBelow(anchor.getBoundingClientRect(), SESSION_MENU_WIDTH));
  };

  const organize = (patch: SessionOrganizationPatch) => {
    if (!sessionId) return;
    void updateSessionOrganization(sessionId, patch, workspaceId)
      .then(onOrganized)
      .catch((error: unknown) =>
        notify(error instanceof Error ? error.message : t("Couldn't update this chat"), {
          tone: "error",
        }),
      );
  };

  const moveToWorkspace = (destination: string | null) => {
    if (!sessionId || moving) return;
    setMoving(true);
    void updateSessionOrganization(sessionId, { workspace_id: destination }, workspaceId)
      .then(onMoved)
      .catch((error: unknown) =>
        notify(error instanceof Error ? error.message : t("Couldn't update this chat"), {
          tone: "error",
        }),
      )
      .finally(() => setMoving(false));
  };

  const remove = () => {
    if (!sessionId) return;
    if (
      !window.confirm(
        t("Permanently delete this chat and its tutor threads? This cannot be undone."),
      )
    ) {
      return;
    }
    void deleteSession(sessionId, workspaceId)
      .then(onDeleted)
      .catch((error: unknown) =>
        notify(error instanceof Error ? error.message : t("Couldn't delete this chat"), {
          tone: "error",
        }),
      );
  };

  const session: SessionOrganization | null = sessionId
    ? (row ?? {
        session_id: sessionId,
        title,
        preferences: { workspace_id: workspaceId || null },
      })
    : null;
  const taskLinks = sessionId
    ? sessionTaskLinks(taskBoard, sessionId, workspaceId)
    : null;

  return (
    <>
      <HeaderActionButton
        ref={anchorRef}
        onClick={toggle}
        disabled={!sessionId}
        icon={MoreHorizontal}
        label={t("Conversation actions")}
        title={sessionId ? t("Conversation actions") : t("Start a conversation first")}
        menuOpen={open}
      />
      {open && position && session && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={menuRef}
              role="menu"
              aria-label={t("Conversation actions")}
              style={{
                left: position.left,
                top: position.top,
                maxHeight: position.maxHeight,
                transformOrigin: "top right",
              }}
              className={SESSION_MENU_SURFACE}
            >
              <SessionActionsMenuItems
                session={session}
                workspaces={workspaces}
                live={live}
                moving={moving}
                onRename={onRename}
                onOrganize={organize}
                onMoveWorkspace={moveToWorkspace}
                onDelete={remove}
                onDone={close}
                extra={
                  <>
                    {taskLinks?.task_ids.length ? (
                      <SessionMenuItem
                        icon={Unlink}
                        label={t(
                          taskLinks.status_link_enabled
                            ? "tasks.unlinkStatus"
                            : "tasks.linkStatus",
                        )}
                        onClick={() => {
                          close();
                          void setTaskStatusLink(
                            session.session_id,
                            workspaceId,
                            !taskLinks.status_link_enabled,
                          ).catch(() => notify(t("tasks.saveError"), { tone: "error" }));
                        }}
                      />
                    ) : null}
                    <SessionMenuDivider />
                    <SessionMenuItem
                      icon={BookmarkPlus}
                      label={t("Save to Notebook")}
                      disabled={!canSave}
                      onClick={() => {
                        close();
                        onSave();
                      }}
                    />
                    <SessionMenuItem
                      icon={Download}
                      label={t("Download Markdown")}
                      disabled={!canExport}
                      onClick={() => {
                        close();
                        onExport();
                      }}
                    />
                  </>
                }
              />
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

"use client";

/**
 * The actions one conversation offers, wherever it is offered from: its row
 * in a session list, or the chat header's "⋯". Both render these items so a
 * conversation reads the same from either side; each caller owns its own
 * floating surface and adds what only it can do (``extra``, ``footer``).
 */

import type { ReactNode } from "react";
import {
  Archive,
  ArchiveRestore,
  Check,
  Folder,
  FolderOpen,
  Pencil,
  Pin,
  PinOff,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  SessionOrganizationPatch,
  SessionSummary,
} from "@/lib/session-api";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";

/** The floating card both surfaces draw these items on. */
export const SESSION_MENU_SURFACE =
  "fixed z-[100] w-60 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--popover)] p-2 text-[12px] shadow-xl";

export const SESSION_MENU_WIDTH = 240;

export function SessionMenuItem({
  icon: Icon,
  label,
  checked = false,
  danger = false,
  disabled = false,
  onClick,
}: {
  icon?: LucideIcon;
  label: string;
  checked?: boolean;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-[var(--muted)] disabled:opacity-50 ${
        danger ? "text-[var(--destructive)]" : "text-[var(--foreground)]"
      }`}
    >
      {Icon ? (
        <Icon size={13} strokeWidth={1.7} />
      ) : (
        <span className="w-3" />
      )}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {checked ? <Check size={12} /> : null}
    </button>
  );
}

export function SessionMenuDivider() {
  return <div className="my-1 border-t border-[var(--border)]/70" />;
}

export function SessionMenuCaption({ children }: { children: ReactNode }) {
  return (
    <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]/65">
      {children}
    </div>
  );
}

/** What the menu reads of a conversation: a list row has it, and so does the
 *  detail an organization write returns. */
export type SessionMenuTarget = Pick<
  SessionSummary,
  "session_id" | "preferences" | "status" | "content_workspace_id"
>;

export function SessionActionsMenuItems({
  session,
  workspaces,
  live = false,
  moving = false,
  renaming = false,
  onRename,
  onOrganize,
  onMoveWorkspace,
  onDelete,
  onDone,
  extra,
  footer,
}: {
  session: SessionMenuTarget;
  workspaces: ChatWorkspaceRegistration[];
  /** A turn is streaming: the conversation cannot change stores mid-turn. */
  live?: boolean;
  /** A workspace move is already in flight. */
  moving?: boolean;
  /** The title is being edited right now. */
  renaming?: boolean;
  onRename: () => void;
  onOrganize: (patch: SessionOrganizationPatch) => void;
  onMoveWorkspace: (workspaceId: string | null) => void;
  onDelete: () => void;
  /** Close the menu once an action is taken. */
  onDone: () => void;
  /** Caller-specific actions, after pin / archive. */
  extra?: ReactNode;
  /** Caller-specific actions, just above delete. */
  footer?: ReactNode;
}) {
  const { t } = useTranslation();
  const archived = Boolean(session.preferences?.archived);
  const pinned = Boolean(session.preferences?.pinned);
  // Same reading as ``sessionWorkspaceId``: the store a row was read from
  // wins over a preference that may predate a move.
  const workspaceId =
    session.content_workspace_id ?? session.preferences?.workspace_id ?? "";
  const running = live || session.status === "running";
  // Close first: delete asks for confirmation, and that dialog should not
  // sit on top of a menu still hanging open behind it.
  const act = (run: () => void) => () => {
    onDone();
    run();
  };

  return (
    <>
      <SessionMenuItem
        icon={renaming ? Check : Pencil}
        label={t("Rename chat")}
        onClick={act(onRename)}
      />
      <SessionMenuItem
        icon={pinned ? PinOff : Pin}
        label={pinned ? t("Unpin") : t("Pin")}
        onClick={act(() => onOrganize({ pinned: !pinned }))}
      />
      <SessionMenuItem
        icon={archived ? ArchiveRestore : Archive}
        label={archived ? t("Restore from archive") : t("Archive")}
        onClick={act(() => onOrganize({ archived: !archived }))}
      />
      {extra}
      {/* Filing a conversation from the list it is filed in. Archived
          workspaces are left out: they keep the conversations they have and
          stop taking new ones. */}
      {workspaceId ||
      workspaces.some(
        (workspace) => workspace.kind === "workspace" && !workspace.archived,
      ) ? (
        <>
          <SessionMenuDivider />
          <SessionMenuCaption>{t("Move to workspace")}</SessionMenuCaption>
          <SessionMenuItem
            icon={FolderOpen}
            label={t("General workspace")}
            disabled={moving || running}
            checked={!workspaceId}
            onClick={act(() => onMoveWorkspace(null))}
          />
          <div>
            {workspaces
              .filter(
                (workspace) =>
                  workspace.kind === "workspace" &&
                  (!workspace.archived ||
                    workspace.workspace_id === workspaceId),
              )
              .map((workspace) => (
                <SessionMenuItem
                  key={workspace.workspace_id}
                  icon={Folder}
                  label={workspace.display_name}
                  disabled={
                    moving ||
                    workspace.archived ||
                    workspace.status !== "ready" ||
                    running
                  }
                  checked={workspaceId === workspace.workspace_id}
                  onClick={act(() => onMoveWorkspace(workspace.workspace_id))}
                />
              ))}
          </div>
        </>
      ) : null}
      {footer}
      <SessionMenuDivider />
      <SessionMenuItem
        icon={Trash2}
        label={t("Delete chat")}
        danger
        onClick={act(onDelete)}
      />
    </>
  );
}

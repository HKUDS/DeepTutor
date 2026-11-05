"use client";

import Tooltip from "@/shared/ui/Tooltip";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ChevronDown,
  ChevronRight,
  MessagesSquare,
  MoreHorizontal,
  Unlink,
  Pin,
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  deriveSessionMark,
  sessionKindOf,
  SessionAvatar,
} from "@/components/sidebar/SessionAvatar";
import { useTaskBoard } from "@/lib/task-board-store";
import { sessionTaskLinks, setTaskStatusLink } from "@/lib/task-board-api";
import { notify } from "@/lib/notifications";
import { useUnreadSessions } from "@/lib/session-unread";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";
import type { MasteryTopicLabel } from "@/lib/learning-api";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";
import type {
  SessionOrganizationPatch,
  SessionSummary,
} from "@/lib/session-api";
import { sessionWorkspaceId } from "@/lib/session-api";
import { organizeSessionTree } from "@/lib/session-organization";
import { matches } from "@/components/sidebar/NavigationPrimitives";
import {
  RecordGroups,
  RecordTime,
  type RecordView,
} from "@/components/sidebar/RecordList";
import {
  displaySessionTitle,
  isPlaceholderSessionTitle,
} from "@/lib/session-title";
import { useDragSort } from "@/hooks/useDragSort";
import { placeMenu, type FloatingMenuPosition } from "@/lib/floating-menu";
import {
  SESSION_MENU_SURFACE,
  SESSION_MENU_WIDTH,
  SessionActionsMenuItems,
  SessionMenuDivider,
  SessionMenuItem,
} from "@/components/sessions/SessionActionsMenu";
import {
  buildSidebarEntries,
  type SidebarGroupEntry,
} from "@/lib/sidebar-entries";
import {
  readCollapsedGroups,
  writeCollapsedGroups,
} from "@/lib/sidebar-layout";

interface OrganizedSessionListProps {
  sessions: SessionSummary[];
  /**
   * Workspaces a conversation can be filed into from its row menu. Omit where
   * there is nothing to move between (the space history) and
   * the menu keeps the block out.
   */
  workspaces?: ChatWorkspaceRegistration[];
  /** Fold every conversation under one "Recent" heading. */
  recents?: boolean;
  /**
   * The sidebar's record view: conversations by day, in the chosen order,
   * filtered by its search — the same shape as the learning and partner
   * records. Hand ordering and groups do not apply there.
   */
  timeline?: RecordView;
  /** Show each row's last activity, as the record lists do, without grouping by day. */
  times?: boolean;
  /** Topics whose study conversations get their own group. Omit for none. */
  masteryTopics?: MasteryTopicLabel[];
  /** Collections whose reading conversations get their own group. */
  readingCollections?: ReadingCollectionLabel[];
  activeSessionId: string | null;
  /**
   * Conversations the caller is streaming right now. They sort above the rest
   * (see ``organizeSessionTree``) — this list is only refetched when a turn
   * ends, so without it the conversation you are waiting on can sit halfway
   * down under a timestamp from last week.
   */
  liveSessionIds?: ReadonlySet<string>;
  emptyLabel?: string;
  nested?: boolean;
  onSelect: (sessionId: string) => void | Promise<void>;
  onRename: (sessionId: string, title: string) => void | Promise<void>;
  onDelete: (sessionId: string) => void | Promise<void>;
  onOrganize: (
    sessionId: string,
    patch: SessionOrganizationPatch,
  ) => void | Promise<void>;
  /**
   * Hand-arranged order of the top-level entries — conversation ids and group
   * ids in one list. Needed here as well as at the caller because
   * ``organizeSessionTree`` sorts roots by pin, activity and recency; without
   * it a dragged entry would snap back on the next render.
   */
  manualOrder?: readonly string[];
  /** Enables dragging the top-level entries; receives their new order. */
  onReorder?: (entryIds: string[]) => void;
  /** Drops the hand-arranged order and returns the list to recency. */
  onResetOrder?: () => void;
  /** The scrolling ancestor, so a drag can reach rows past the fold. */
  scrollRef?: React.RefObject<HTMLElement | null>;
}


export default function OrganizedSessionList({
  sessions,
  workspaces = [],
  recents = false,
  timeline,
  times = false,
  masteryTopics = [],
  readingCollections = [],
  activeSessionId,
  liveSessionIds,
  emptyLabel,
  nested = true,
  onSelect,
  onRename,
  onDelete,
  onOrganize,
  manualOrder,
  onReorder,
  onResetOrder,
  scrollRef,
}: OrganizedSessionListProps) {
  // Reads the set; `SessionList` owns keeping it current.
  const unread = useUnreadSessions();
  const { t } = useTranslation();
  const { board: taskBoard } = useTaskBoard();
  // Backend writes the English sentinel "New conversation" until the LLM
  // title lands; mirror SessionList by showing a localized, breathing label.
  const placeholderLabel = t("New chat");
  const [workspaceMoveError, setWorkspaceMoveError] = useState("");
  const [movingWorkspace, setMovingWorkspace] = useState(false);
  const [groupLimits, setGroupLimits] = useState<Record<string, number>>({});
  const moveToWorkspace = async (sessionId: string, workspaceId: string | null) => {
    if (movingWorkspace) return;
    setMovingWorkspace(true);
    setWorkspaceMoveError("");
    try {
      await onOrganize(sessionId, { workspace_id: workspaceId });
    } catch (err) {
      setWorkspaceMoveError(err instanceof Error ? err.message : String(err));
    } finally {
      setMovingWorkspace(false);
    }
  };
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [menuPosition, setMenuPosition] = useState<FloatingMenuPosition | null>(
    null,
  );
  const [collapsedParents, setCollapsedParents] = useState<Set<string>>(
    new Set(),
  );
  const menuRootRef = useRef<HTMLDivElement>(null);
  const menuAnchorRef = useRef<HTMLButtonElement | null>(null);

  const { roots, childrenByParent } = useMemo(
    () => organizeSessionTree(sessions, nested, liveSessionIds),
    [liveSessionIds, nested, sessions],
  );

  // Whether to reserve the disclosure column at all.
  //
  // Every row used to hold 18px open for a caret that only a conversation with
  // tutor threads under it ever draws — and the sidebar is handed its list with
  // those threads already filtered out, so there the column could never be
  // filled: every dot and every title sat a fifth of the panel's width in for
  // nothing. It is reserved when this particular list has something expandable
  // in it, which keeps titles aligned on the surfaces that do (the history console) and hands the sidebar its left edge back.
  const hasThreads = childrenByParent.size > 0;

  /* One list, conversations and groups at the same level.
   *
   * A mastery topic and a reading collection are each a single unit here, sat
   * in the slot of the newest conversation inside them, so the region reads by
   * recency all the way down whatever surface the work happened on.
   *
   * The whole list is arrangeable by hand, groups included: what sits at the
   * top of a sidebar is the learner's call, and the two kinds are peers. */
  const entries = useMemo(
    () =>
      buildSidebarEntries({
        roots,
        recents,
        masteryTopics,
        readingCollections,
        manualOrder,
      }),
    [recents, manualOrder, masteryTopics, readingCollections, roots],
  );

  const entryIds = useMemo(() => entries.map((entry) => entry.id), [entries]);
  const drag = useDragSort({
    ids: entryIds,
    disabled: !onReorder,
    onReorder: (next) => onReorder?.(next),
    scrollRef,
  });
  // One collapse set for every kind of group — topic or collection.
  // Their ids never collide, and a learner folding a group shut does not care
  // which table it came from. Persisted, so a sidebar arranged once stays
  // arranged across reloads.
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    new Set(),
  );
  // The ref carries the live set: two headings toggled inside one render pass
  // would otherwise both start from the same stale state and the first would
  // be lost.
  const collapsedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const stored = new Set(readCollapsedGroups());
    collapsedRef.current = stored;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCollapsedGroups(stored);
  }, []);

  const toggleGroup = (groupId: string) => {
    const next = new Set(collapsedRef.current);
    if (next.has(groupId)) next.delete(groupId);
    else next.add(groupId);
    collapsedRef.current = next;
    setCollapsedGroups(next);
    writeCollapsedGroups([...next]);
  };

  useEffect(() => {
    if (!openMenuId) return;
    const closeMenu = () => {
      setOpenMenuId(null);
      setMenuPosition(null);
    };
    const close = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        !menuRootRef.current?.contains(target) &&
        !menuAnchorRef.current?.contains(target)
      ) {
        closeMenu();
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };
    const closeOnViewportChange = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && menuRootRef.current?.contains(target))
        return;
      closeMenu();
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeMenu);
    window.addEventListener("scroll", closeOnViewportChange, true);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeMenu);
      window.removeEventListener("scroll", closeOnViewportChange, true);
    };
  }, [openMenuId]);

  const commitEdit = async () => {
    if (!editingId) return;
    const next = draftTitle.trim();
    if (next) await onRename(editingId, next);
    setEditingId(null);
    setDraftTitle("");
  };

  const toggleChildren = (sessionId: string) => {
    setCollapsedParents((previous) => {
      const next = new Set(previous);
      if (next.has(sessionId)) next.delete(sessionId);
      else next.add(sessionId);
      return next;
    });
  };

  if (entries.length === 0) {
    return (
      <div className="px-3 py-2 text-[11px] text-[var(--muted-foreground)]/65">
        {emptyLabel ?? t("No conversations yet")}
      </div>
    );
  }

  const renderRow = (session: SessionSummary, child = false) => {
    const active = activeSessionId === session.session_id;
    const editing = editingId === session.session_id;
    const children = childrenByParent.get(session.session_id) ?? [];
    const expanded =
      children.length > 0 && !collapsedParents.has(session.session_id);
    const menuOpen = openMenuId === session.session_id;
    const pinned = Boolean(session.preferences?.pinned);
    const taskLinks = sessionTaskLinks(
      taskBoard, session.session_id, sessionWorkspaceId(session),
    );

    return (
      <div key={session.session_id} className="relative">
        <div
          role="button"
          tabIndex={0}
          onClick={() => void onSelect(session.session_id)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              void onSelect(session.session_id);
            }
          }}
          className={`group/session flex min-w-0 items-center gap-1.5 rounded-lg py-1.5 pr-1 transition-colors ${
            child ? "ml-4 border-l border-[var(--border)]/60 pl-2" : "pl-1.5"
          } ${
            active
              ? "bg-background/60 text-[var(--foreground)]"
              : "text-[var(--foreground)] hover:bg-background/40"
          }`}
        >
          {children.length > 0 ? (
            <button
              type="button"
              data-no-drag
              onClick={(event) => {
                event.stopPropagation();
                toggleChildren(session.session_id);
              }}
              className="rounded p-0.5 hover:bg-[var(--muted)]"
              aria-label={
                expanded ? t("Hide tutor threads") : t("Show tutor threads")
              }
              aria-expanded={expanded}
            >
              <ChevronRight
                size={11}
                className={`transition-transform ${expanded ? "rotate-90" : ""}`}
              />
            </button>
          ) : hasThreads ? (
            <span className="w-3" />
          ) : null}
          <SessionAvatar
            sessionId={session.session_id}
            workspaceId={sessionWorkspaceId(session)}
            mark={deriveSessionMark(session, liveSessionIds, unread)}
            kind={sessionKindOf(session)}
            size={child ? 11 : 12}
            className={child ? "opacity-65" : "opacity-80"}
          />
          {child ? (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[var(--muted)]/70 px-1.5 py-0.5 text-[9px] font-medium text-[var(--muted-foreground)]">
              <MessagesSquare size={9} strokeWidth={1.8} />
              {t("Side chat")}
            </span>
          ) : null}
          {editing ? (
            <input
              value={draftTitle}
              autoFocus
              data-no-drag
              onChange={(event) => setDraftTitle(event.target.value)}
              onBlur={() => void commitEdit()}
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => {
                event.stopPropagation();
                if (event.key === "Enter") void commitEdit();
                if (event.key === "Escape") setEditingId(null);
              }}
              className="min-w-0 flex-1 rounded border border-[var(--border)] bg-[var(--background)] px-1.5 py-0.5 text-[12px] outline-none focus:border-[var(--ring)]"
            />
          ) : (
            <Tooltip
              label={`${t("Conversation")}: ${isPlaceholderSessionTitle(session.title) ? placeholderLabel : session.title}`}
              side="top"
              className="min-w-0 flex-1"
            >
              <span
                className={isPlaceholderSessionTitle(session.title)
                  ? "dt-breathing-text min-w-0 flex-1 truncate text-[12.5px] italic text-[var(--foreground)]"
                  : "min-w-0 flex-1 truncate text-[12.5px]"}
              >
                {displaySessionTitle(session.title, placeholderLabel)}
              </span>
            </Tooltip>
          )}
          {pinned ? <Pin size={10} className="shrink-0 opacity-55" /> : null}
          {children.length > 0 && !expanded ? (
            <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 text-[9px] tabular-nums">
              {children.length}
            </span>
          ) : null}
          {timeline || times ? (
            // The time gives way to the actions under the pointer or focus.
            <span className="relative flex shrink-0 items-center justify-end">
              <RecordTime
                seconds={timeline?.sort === "createdAt" ? session.created_at : session.updated_at}
                className={menuOpen ? "invisible" : "group-hover/session:invisible group-focus-within/session:invisible"}
              />
              <button
                type="button"
                data-no-drag
                onClick={(event) => {
                  event.stopPropagation();
                  if (menuOpen) {
                    setOpenMenuId(null);
                    setMenuPosition(null);
                    return;
                  }
                  menuAnchorRef.current = event.currentTarget;
                  setMenuPosition(
                    placeMenu(
                      event.currentTarget.getBoundingClientRect(),
                      SESSION_MENU_WIDTH,
                    ),
                  );
                  setOpenMenuId(session.session_id);
                }}
                className={`absolute right-0 rounded p-1 hover:bg-[var(--muted)] ${
                  menuOpen
                    ? "opacity-100"
                    : "opacity-0 group-hover/session:opacity-100 focus:opacity-100"
                }`}
                aria-label={t("Conversation actions")}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
              >
                <MoreHorizontal size={13} />
              </button>
            </span>
          ) : (
            <button
              type="button"
              data-no-drag
              onClick={(event) => {
                event.stopPropagation();
                if (menuOpen) {
                  setOpenMenuId(null);
                  setMenuPosition(null);
                  return;
                }
                menuAnchorRef.current = event.currentTarget;
                setMenuPosition(
                  placeMenu(
                    event.currentTarget.getBoundingClientRect(),
                    SESSION_MENU_WIDTH,
                  ),
                );
                setOpenMenuId(session.session_id);
              }}
              className={`rounded p-1 hover:bg-[var(--muted)] ${timeline ? "absolute right-0" : ""} ${
                menuOpen
                  ? "opacity-100"
                  : "opacity-0 group-hover/session:opacity-100 focus:opacity-100"
              }`}
              aria-label={t("Conversation actions")}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <MoreHorizontal size={13} />
            </button>
          )}
        </div>

        {menuOpen && menuPosition && typeof document !== "undefined"
          ? createPortal(
              <div
                ref={menuRootRef}
                role="menu"
                style={{
                  left: menuPosition.left,
                  top: menuPosition.top,
                  maxHeight: menuPosition.maxHeight,
                  transform: menuPosition.openUpward
                    ? "translateY(-100%)"
                    : undefined,
                  transformOrigin: menuPosition.openUpward ? "bottom" : "top",
                }}
                className={SESSION_MENU_SURFACE}
              >
                <SessionActionsMenuItems
                  session={session}
                  workspaces={workspaces}
                  live={liveSessionIds?.has(session.session_id)}
                  moving={movingWorkspace}
                  renaming={editing}
                  onRename={() => {
                    setDraftTitle(session.title);
                    setEditingId(session.session_id);
                  }}
                  onOrganize={(patch) => void onOrganize(session.session_id, patch)}
                  onMoveWorkspace={(workspaceId) =>
                    void moveToWorkspace(session.session_id, workspaceId)
                  }
                  onDelete={() => void onDelete(session.session_id)}
                  onDone={() => {
                    setOpenMenuId(null);
                    setMenuPosition(null);
                  }}
                  extra={
                    taskLinks?.task_ids.length ? (
                      <SessionMenuItem
                        icon={Unlink}
                        label={t(taskLinks.status_link_enabled ? "tasks.unlinkStatus" : "tasks.linkStatus")}
                        onClick={() => {
                          void setTaskStatusLink(
                            session.session_id,
                            sessionWorkspaceId(session),
                            !taskLinks.status_link_enabled,
                          ).catch(() => notify(t("tasks.saveError"), { tone: "error" }));
                          setOpenMenuId(null);
                          setMenuPosition(null);
                        }}
                      />
                    ) : null
                  }
                  footer={
                    onResetOrder && (manualOrder?.length ?? 0) > 0 ? (
                      <>
                        <SessionMenuDivider />
                        <SessionMenuItem
                          icon={RotateCcw}
                          label={t("Reset chat order")}
                          onClick={() => {
                            setOpenMenuId(null);
                            setMenuPosition(null);
                            onResetOrder();
                          }}
                        />
                      </>
                    ) : null
                  }
                />
              </div>,
              document.body,
            )
          : null}

        {expanded ? children.map((row) => renderRow(row, true)) : null}
      </div>
    );
  };

  /** A conversation row wrapped in the drag layer. */
  const renderSortableRow = (session: SessionSummary) => {
    if (!onReorder) return renderRow(session);
    const { style, ...handlers } = drag.getItemProps(session.session_id);
    const dragging = drag.draggingId === session.session_id;
    return (
      <div
        key={session.session_id}
        data-session-id={session.session_id}
        {...handlers}
        style={style}
        className={`rounded-lg ${
          dragging
            ? "bg-background/85 shadow-lg ring-1 ring-border/70"
            : ""
        }`}
      >
        {renderRow(session)}
      </div>
    );
  };

  /**
   * A collapsible group — a mastery topic or a reading collection —
   * standing at the same level as a single conversation, and dragged like one.
   *
   * Only the heading takes the press that starts a drag: grabbing a group by
   * one of its rows and watching the whole block move is not what that press
   * meant. The wrapper is still what the drag measures and shifts, so the gap a
   * dragged group leaves behind is its real height — which is also why its
   * spacing is padding rather than margin, since a margin sits outside the box
   * the drag measures.
   */
  const renderGroup = (entry: SidebarGroupEntry) => {
    const collapsed = collapsedGroups.has(entry.id);
    const recent = entry.group === "recent";
    const limit = recent ? groupLimits[entry.id] ?? 5 : entry.rows.length;
    // Keep the active conversation visible, including older deep links.
    const activeIndex = entry.rows.findIndex(row => row.session_id === activeSessionId);
    const visibleRows = entry.rows.slice(0, limit);
    if (activeIndex >= limit && visibleRows.length) {
      visibleRows[visibleRows.length - 1] = entry.rows[activeIndex];
    }
    const sortable = Boolean(onReorder);
    const { style, ...handlers } = drag.getItemProps(entry.id);
    const dragging = drag.draggingId === entry.id;
    return (
      <div
        key={entry.id}
        data-group-id={entry.id}
        ref={sortable ? handlers.ref : undefined}
        style={sortable ? style : undefined}
        className={`${recent ? "pt-5" : "pt-1.5"} first:pt-0 ${
          dragging
            ? "rounded-lg bg-background/85 shadow-lg ring-1 ring-border/70"
            : ""
        }`}
      >
        <button
          type="button"
          onPointerDown={sortable ? handlers.onPointerDown : undefined}
          onClickCapture={sortable ? handlers.onClickCapture : undefined}
          onKeyDown={sortable ? handlers.onKeyDown : undefined}
          onDragStartCapture={
            sortable ? handlers.onDragStartCapture : undefined
          }
          onClick={() => toggleGroup(entry.id)}
          aria-expanded={!collapsed}
          // A quiet title, not a section banner: the same size and the same ink
          // as the conversation titles it sits among, one weight heavier, with
          // its mark column holding the two in one left edge. Earlier passes
          // had it a hair smaller than a caption and uppercase, which shouted
          // in a list of 12.5px rows and did nothing whatsoever to the CJK
          // titles most of these groups actually carry.
          className="group/heading flex w-full min-w-0 items-center gap-1.5 rounded-lg px-1.5 py-1 text-left text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-background/40 hover:text-[var(--foreground)]"
        >
          {!recent && <GroupMark />}
          <span className="min-w-0 truncate">{recent ? t("Recent") : entry.label}</span>
          {/* The caret follows the words rather than introducing them — a
              title that can be folded, instead of a row of controls with a
              label attached. */}
          <ChevronDown
            size={11}
            strokeWidth={2}
            className={`shrink-0 opacity-50 transition-[transform,opacity] duration-150 group-hover/heading:opacity-80 ${
              collapsed ? "-rotate-90" : ""
            }`}
          />
          <span className="flex-1" />
          {/* Only while folded. An open group has its conversations on screen;
              counting them for the reader is a number that says nothing. */}
          {collapsed ? (
            <span className="shrink-0 text-[10.5px] tabular-nums opacity-50">
              {entry.rows.length}
            </span>
          ) : null}
        </button>
        {collapsed ? null : (
          <div className={recent ? "" : "ml-1.5 border-l border-[var(--border)]/40 pl-1"}>
            {visibleRows.map((session) => renderRow(session))}
            {entry.rows.length > limit && (
              <button type="button" className="px-2 py-1 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                onClick={() => setGroupLimits(previous => ({ ...previous, [entry.id]: limit + 5 }))}>
                {t("Show more")}
              </button>
            )}
          </div>
        )}
      </div>
    );
  };

  if (timeline) {
    const time = (row: SessionSummary) =>
      timeline.sort === "createdAt" ? row.created_at : row.updated_at;
    const found = roots.filter((row) =>
      matches(displaySessionTitle(row.title, placeholderLabel), timeline.query),
    );
    return (
      <div className="py-0.5">
        {workspaceMoveError && <p role="alert" className="px-2 py-1 text-xs text-[var(--destructive)]">{workspaceMoveError}</p>}
        <RecordGroups
          rows={found
            .filter((row) => !row.preferences?.pinned)
            .sort((a, b) => time(b) - time(a))}
          lead={{
            label: t("navigation.pinned"),
            rows: found.filter((row) => row.preferences?.pinned),
          }}
          view={timeline}
          time={time}
          renderRow={(row) => renderRow(row)}
          empty={
            <p className="dt-navigation-empty">
              {timeline.query ? t("navigation.noResults") : emptyLabel ?? t("navigation.noSessions")}
            </p>
          }
        />
      </div>
    );
  }

  return (
    <div className="py-0.5">
      {workspaceMoveError && <p role="alert" className="px-2 py-1 text-xs text-[var(--destructive)]">{workspaceMoveError}</p>}
      {entries.map((entry) =>
        entry.kind === "group"
          ? renderGroup(entry)
          : renderSortableRow(entry.session),
      )}

    </div>
  );
}

/**
 * What a group wears in the column where its conversations carry their status
 * mark.
 *
 * Mastery paths and reading collections used to show a lucide glyph here
 * (`Route` / `BookText`). At 12px those sat in the same column as a session's
 * status mark, at the same size, in an entirely different visual language —
 * which is what made a mixed list read as two lists spliced together. A
 * group's own title already says what kind of group it is, so the column is
 * simply left empty for them.
 *
 * The fixed-width box is what holds the alignment — group titles and
 * conversation titles start at the same x whether or not anything is drawn.
 */
function GroupMark() {
  return <span className="flex w-3 shrink-0 items-center justify-center" />;
}

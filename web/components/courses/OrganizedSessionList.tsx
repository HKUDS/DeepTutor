"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Archive,
  ArchiveRestore,
  Check,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  GraduationCap,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  deriveSessionMark,
  SessionAvatar,
} from "@/components/sidebar/SessionAvatar";
import { useUnreadSessions } from "@/lib/session-unread";
import type { StudyCourse } from "@/lib/courses-api";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";
import type { MasteryTopicLabel } from "@/lib/learning-api";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";
import type {
  SessionOrganizationPatch,
  SessionSummary,
} from "@/lib/session-api";
import { sessionWorkspaceId } from "@/lib/session-api";
import { organizeSessionTree } from "@/lib/session-organization";
import {
  displaySessionTitle,
  isPlaceholderSessionTitle,
} from "@/lib/session-title";
import { useDragSort } from "@/hooks/useDragSort";
import { placeMenu, type FloatingMenuPosition } from "@/lib/floating-menu";
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
  courses: StudyCourse[];
  /**
   * Workspaces a conversation can be filed into from its row menu. Omit where
   * there is nothing to move between (the course page, the space history) and
   * the menu keeps the block out.
   */
  workspaces?: ChatWorkspaceRegistration[];
  /** Account sidebar only; scoped lists already live within a workspace. */
  groupWorkspaces?: boolean;
  onNewWorkspaceChat?: (workspaceId: string) => void;
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

const MENU_WIDTH = 240;

export default function OrganizedSessionList({
  sessions,
  courses,
  workspaces = [],
  groupWorkspaces = false,
  onNewWorkspaceChat,
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
  // in it, which keeps titles aligned on the surfaces that do (a course page,
  // the history console) and hands the sidebar its left edge back.
  const hasThreads = childrenByParent.size > 0;

  /* One list, conversations and groups at the same level.
   *
   * A mastery topic and a reading collection are each a single unit here, sat
   * in the slot of the newest conversation inside them, so the region reads by
   * recency all the way down whatever surface the work happened on. Courses
   * group the same way — assigning a conversation to one used to be write-only,
   * and filing you cannot read back is not filing.
   *
   * The whole list is arrangeable by hand, groups included: what sits at the
   * top of a sidebar is the learner's call, and the two kinds are peers. */
  const entries = useMemo(
    () =>
      buildSidebarEntries({
        roots,
        courses,
        workspaces: groupWorkspaces ? workspaces : undefined,
        masteryTopics,
        readingCollections,
        manualOrder,
      }),
    [courses, workspaces, groupWorkspaces, manualOrder, masteryTopics, readingCollections, roots],
  );

  const entryIds = useMemo(() => entries.map((entry) => entry.id), [entries]);
  const drag = useDragSort({
    ids: entryIds,
    disabled: !onReorder,
    onReorder: (next) => onReorder?.(next),
    scrollRef,
  });
  // One collapse set for every kind of group — topic, collection, course.
  // Their ids never collide, and a learner folding a group shut does not care
  // which table it came from. Persisted, so a sidebar arranged once stays
  // arranged across reloads.
  const [collapsedCourses, setCollapsedCourses] = useState<Set<string>>(
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
    setCollapsedCourses(stored);
  }, []);

  const toggleCourse = (courseId: string) => {
    const next = new Set(collapsedRef.current);
    if (next.has(courseId)) next.delete(courseId);
    else next.add(courseId);
    collapsedRef.current = next;
    setCollapsedCourses(next);
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
    const archived = Boolean(session.preferences?.archived);
    const pinned = Boolean(session.preferences?.pinned);

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
              ? "bg-[var(--background)]/60 text-[var(--foreground)]"
              : "text-[var(--foreground)] hover:bg-[var(--background)]/40"
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
            mark={deriveSessionMark(session, liveSessionIds, unread)}
            size={child ? 11 : 12}
            className={child ? "opacity-65" : "opacity-80"}
          />
          {child ? (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[var(--muted)]/70 px-1.5 py-0.5 text-[9px] font-medium text-[var(--muted-foreground)]">
              <GraduationCap size={9} strokeWidth={1.8} />
              {t("Little Tutor")}
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
          ) : isPlaceholderSessionTitle(session.title) ? (
            <span
              className="dt-breathing-text min-w-0 flex-1 truncate text-[12.5px] italic text-[var(--foreground)]"
              title={placeholderLabel}
            >
              {displaySessionTitle(session.title, placeholderLabel)}
            </span>
          ) : (
            <span
              className="min-w-0 flex-1 truncate text-[12.5px]"
              title={session.title}
            >
              {displaySessionTitle(session.title, placeholderLabel)}
            </span>
          )}
          {pinned ? <Pin size={10} className="shrink-0 opacity-55" /> : null}
          {children.length > 0 && !expanded ? (
            <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 text-[9px] tabular-nums">
              {children.length}
            </span>
          ) : null}
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
                  MENU_WIDTH,
                ),
              );
              setOpenMenuId(session.session_id);
            }}
            className={`rounded p-1 hover:bg-[var(--muted)] ${
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
                className="fixed z-[100] w-60 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--popover)] p-2 text-[12px] shadow-xl"
              >
                <MenuButton
                  icon={editing ? Check : Pencil}
                  label={t("Rename chat")}
                  onClick={() => {
                    setDraftTitle(session.title);
                    setEditingId(session.session_id);
                    setOpenMenuId(null);
                    setMenuPosition(null);
                  }}
                />
                <MenuButton
                  icon={pinned ? PinOff : Pin}
                  label={pinned ? t("Unpin") : t("Pin")}
                  onClick={() => {
                    void onOrganize(session.session_id, { pinned: !pinned });
                    setOpenMenuId(null);
                    setMenuPosition(null);
                  }}
                />
                <MenuButton
                  icon={archived ? ArchiveRestore : Archive}
                  label={archived ? t("Restore from archive") : t("Archive")}
                  onClick={() => {
                    void onOrganize(session.session_id, {
                      archived: !archived,
                    });
                    setOpenMenuId(null);
                    setMenuPosition(null);
                  }}
                />
                {courses.length > 0 ? (
                  <>
                    <div className="my-1 border-t border-[var(--border)]/70" />
                    <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]/65">
                      {t("Move to course")}
                    </div>
                    <MenuButton
                      icon={GraduationCap}
                      label={t("Unclassified")}
                      checked={!session.preferences?.course_id}
                      onClick={() => {
                        void onOrganize(session.session_id, { course_id: "" });
                        setOpenMenuId(null);
                        setMenuPosition(null);
                      }}
                    />
                    <div>
                      {courses.map((course) => (
                        <MenuButton
                          key={course.id}
                          color={course.color}
                          label={course.name}
                          checked={session.preferences?.course_id === course.id}
                          onClick={() => {
                            void onOrganize(session.session_id, {
                              course_id: course.id,
                            });
                            setOpenMenuId(null);
                            setMenuPosition(null);
                          }}
                        />
                      ))}
                    </div>
                  </>
                ) : null}
                {/* Filing a conversation from the list it is filed in.
                    Archived workspaces are left out: they keep the
                    conversations they have and stop taking new ones. */}
                {(sessionWorkspaceId(session) || workspaces.some((workspace) => workspace.kind === "workspace" && !workspace.archived)) ? (
                  <>
                    <div className="my-1 border-t border-[var(--border)]/70" />
                    <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]/65">
                      {t("Move to workspace")}
                    </div>
                    <MenuButton
                      icon={FolderOpen}
                      label={t("No workspace")}
                      disabled={movingWorkspace || session.status === "running" || liveSessionIds?.has(session.session_id)}
                      checked={!sessionWorkspaceId(session)}
                      onClick={() => {
                        void moveToWorkspace(session.session_id, null);
                        setOpenMenuId(null);
                        setMenuPosition(null);
                      }}
                    />
                    <div>
                      {workspaces
                        .filter(
                          (workspace) =>
                            workspace.kind === "workspace" && (!workspace.archived ||
                            workspace.workspace_id ===
                              sessionWorkspaceId(session)),
                        )
                        .map((workspace) => (
                          <MenuButton
                            key={workspace.workspace_id}
                            icon={Folder}
                            label={workspace.display_name}
                            disabled={movingWorkspace || workspace.archived || workspace.status !== "ready" || session.status === "running" || liveSessionIds?.has(session.session_id)}
                            checked={
                              sessionWorkspaceId(session) ===
                              workspace.workspace_id
                            }
                            onClick={() => {
                              void moveToWorkspace(session.session_id, workspace.workspace_id);
                              setOpenMenuId(null);
                              setMenuPosition(null);
                            }}
                          />
                        ))}
                    </div>
                  </>
                ) : null}
                {onResetOrder && (manualOrder?.length ?? 0) > 0 ? (
                  <>
                    <div className="my-1 border-t border-[var(--border)]/70" />
                    <MenuButton
                      icon={RotateCcw}
                      label={t("Reset chat order")}
                      onClick={() => {
                        setOpenMenuId(null);
                        setMenuPosition(null);
                        onResetOrder();
                      }}
                    />
                  </>
                ) : null}
                <div className="my-1 border-t border-[var(--border)]/70" />
                <MenuButton
                  icon={Trash2}
                  label={t("Delete chat")}
                  danger
                  onClick={() => {
                    setOpenMenuId(null);
                    setMenuPosition(null);
                    void onDelete(session.session_id);
                  }}
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
            ? "bg-[var(--background)]/85 shadow-lg ring-1 ring-[var(--border)]/70"
            : ""
        }`}
      >
        {renderRow(session)}
      </div>
    );
  };

  /**
   * A collapsible group — a mastery topic, a reading collection, a course —
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
    const collapsed = collapsedCourses.has(entry.id);
    const recent = entry.group === "recent";
    const limit = entry.group === "workspace" || recent ? groupLimits[entry.id] ?? 5 : entry.rows.length;
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
            ? "rounded-lg bg-[var(--background)]/85 shadow-lg ring-1 ring-[var(--border)]/70"
            : ""
        }`}
      >
        <div className="group/workspace-heading flex items-center">
        <button
          type="button"
          onPointerDown={sortable ? handlers.onPointerDown : undefined}
          onClickCapture={sortable ? handlers.onClickCapture : undefined}
          onKeyDown={sortable ? handlers.onKeyDown : undefined}
          onDragStartCapture={
            sortable ? handlers.onDragStartCapture : undefined
          }
          onClick={() => toggleCourse(entry.id)}
          aria-expanded={!collapsed}
          // A quiet title, not a section banner: the same size and the same ink
          // as the conversation titles it sits among, one weight heavier, with
          // its mark column holding the two in one left edge. Earlier passes
          // had it a hair smaller than a caption and uppercase, which shouted
          // in a list of 12.5px rows and did nothing whatsoever to the CJK
          // titles most of these groups actually carry.
          className="group/heading flex w-full min-w-0 items-center gap-1.5 rounded-lg px-1.5 py-1 text-left text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--background)]/40 hover:text-[var(--foreground)]"
        >
          {!recent && <GroupMark entry={entry} />}
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
        {entry.workspaceId && onNewWorkspaceChat && workspaces.some(workspace =>
          workspace.workspace_id === entry.workspaceId && !workspace.archived && workspace.status === "ready") && (
          <button type="button" className="shrink-0 rounded p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)] sm:opacity-0 group-hover/workspace-heading:opacity-100 focus-visible:opacity-100"
            aria-label={t("New chat in {{name}}", { name: entry.label })}
            onClick={() => onNewWorkspaceChat(entry.workspaceId!)}><Plus size={13} /></button>
        )}
        </div>
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

  // Workspace sections and unassigned Recent chats share the same list level.
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
 * Courses keep their dot: the colour is a real identity (the same one the
 * course wears everywhere else), and at 1.5px it cannot be mistaken for the
 * 7px status mark a conversation carries.
 *
 * The fixed-width box is what holds the alignment — group titles and
 * conversation titles start at the same x whether or not anything is drawn.
 */
function GroupMark({ entry }: { entry: SidebarGroupEntry }) {
  return (
    <span className="flex w-3 shrink-0 items-center justify-center">
      {entry.group === "workspace" ? <FolderOpen size={12} aria-hidden /> : null}
      {entry.group === "course" ? (
        <span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: entry.color }}
        />
      ) : null}
    </span>
  );
}

function MenuButton({
  icon: Icon,
  label,
  color,
  checked = false,
  danger = false,
  disabled = false,
  onClick,
}: {
  icon?: typeof Pencil;
  label: string;
  color?: string;
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
      {color ? (
        <span
          className="h-3 w-1 rounded-full"
          style={{ backgroundColor: color }}
        />
      ) : Icon ? (
        <Icon size={13} strokeWidth={1.7} />
      ) : (
        <span className="w-3" />
      )}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {checked ? <Check size={12} /> : null}
    </button>
  );
}

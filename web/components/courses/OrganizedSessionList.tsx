"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Archive,
  ArchiveRestore,
  BookText,
  Check,
  ChevronRight,
  GraduationCap,
  House,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  RotateCcw,
  Route,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { SessionAvatar } from "@/components/sidebar/SessionAvatar";
import type { StudyCourse } from "@/lib/courses-api";
import type { MasteryTopicLabel } from "@/lib/learning-api";
import type { ReadingCollectionLabel } from "@/lib/reading-workspace-api";
import { masteryPathIdOf, readingWorkspaceIdOf } from "@/lib/mastery-session";
import type {
  SessionOrganizationPatch,
  SessionSummary,
} from "@/lib/session-api";
import { organizeSessionTree } from "@/lib/session-organization";
import { isPlaceholderSessionTitle } from "@/lib/session-title";
import { useDragSort } from "@/hooks/useDragSort";
import { placeMenu, type FloatingMenuPosition } from "@/lib/floating-menu";
import {
  applyManualOrder,
  readCollapsedGroups,
  writeCollapsedGroups,
} from "@/lib/sidebar-layout";

interface OrganizedSessionListProps {
  sessions: SessionSummary[];
  courses: StudyCourse[];
  /** Topics whose study conversations get their own group. Omit for none. */
  masteryTopics?: MasteryTopicLabel[];
  /** Collections whose reading conversations get their own group. */
  readingCollections?: ReadingCollectionLabel[];
  activeSessionId: string | null;
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
   * Hand-arranged order for the ungrouped conversations. Needed here as well
   * as at the caller because ``organizeSessionTree`` sorts roots by pin and
   * recency — without it a dragged row would snap back on the next render.
   */
  manualOrder?: readonly string[];
  /** Enables dragging the ungrouped rows; receives their new order. */
  onReorder?: (sessionIds: string[]) => void;
  /** Drops the hand-arranged order and returns the list to recency. */
  onResetOrder?: () => void;
  /** The scrolling ancestor, so a drag can reach rows past the fold. */
  scrollRef?: React.RefObject<HTMLElement | null>;
}

const MENU_WIDTH = 240;
/** Heading the home conversations live under. A literal, not a real course or
 *  topic id, and shaped so it can never collide with one. */
const CHAT_GROUP_ID = "__chat__";

export default function OrganizedSessionList({
  sessions,
  courses,
  masteryTopics = [],
  readingCollections = [],
  activeSessionId,
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
  const { t } = useTranslation();
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
    () => organizeSessionTree(sessions, nested),
    [nested, sessions],
  );

  /* Roots gathered under the course they belong to.
   *
   * Assigning a conversation to a course used to be write-only: the ⋯ menu
   * could move it, and nothing anywhere then showed where it had gone. Filing
   * you cannot read back is not filing, so the list groups by it — a course is
   * the container everything else in the product hangs off, and this is the one
   * place a learner passes every day.
   *
   * Courses keep the order the shelf gives them (so the sidebar and the Courses
   * page agree), each holding its conversations in their existing recency
   * order; anything unfiled stays at the top, ungrouped, because most
   * conversations never belong to a course and must not be pushed under a
   * heading to reach them.
   */
  const { ungrouped, grouped, masteryGrouped, readingGrouped } = useMemo(() => {
    const byCourse = new Map<string, SessionSummary[]>();
    const byTopic = new Map<string, SessionSummary[]>();
    const byCollection = new Map<string, SessionSummary[]>();
    const loose: SessionSummary[] = [];
    for (const session of roots) {
      // A study conversation files under its topic first. It can also carry a
      // course id — a path reached from a course keeps that link — but the
      // topic is the container it was actually held in, so filing it under
      // the course would put it where the learner never looks for it.
      const topicId = masteryPathIdOf(session);
      if (topicId) {
        const bucket = byTopic.get(topicId);
        if (bucket) bucket.push(session);
        else byTopic.set(topicId, [session]);
        continue;
      }
      // A reading conversation files under the collection it was held in,
      // for the same reason: the reader, its material and its citations are
      // that conversation's context, and it is where the learner looks.
      const collectionId = readingWorkspaceIdOf(session);
      if (collectionId) {
        const bucket = byCollection.get(collectionId);
        if (bucket) bucket.push(session);
        else byCollection.set(collectionId, [session]);
        continue;
      }
      const id = String(session.preferences?.course_id || "");
      if (!id) {
        loose.push(session);
        continue;
      }
      const bucket = byCourse.get(id);
      if (bucket) bucket.push(session);
      else byCourse.set(id, [session]);
    }
    const known = courses
      .filter((course) => byCourse.has(course.id))
      .map((course) => ({ course, rows: byCourse.get(course.id) ?? [] }));
    // A conversation whose course was deleted is unclassified in every other
    // view; hiding it here instead would lose it entirely.
    const knownIds = new Set(courses.map((course) => course.id));
    for (const [id, rows] of byCourse) {
      if (!knownIds.has(id)) loose.push(...rows);
    }
    // Topics keep the index's own order, so the sidebar and the Mastery Path
    // page list them the same way.
    const topics = masteryTopics
      .filter((topic) => byTopic.has(topic.path_id))
      .map((topic) => ({ topic, rows: byTopic.get(topic.path_id) ?? [] }));
    const knownTopicIds = new Set(masteryTopics.map((topic) => topic.path_id));
    for (const [id, rows] of byTopic) {
      if (!knownTopicIds.has(id)) loose.push(...rows);
    }
    // Same rule as topics: a conversation whose collection is gone falls back
    // to the loose list rather than disappearing with its heading.
    const collections = readingCollections
      .filter((collection) => byCollection.has(collection.workspace_id))
      .map((collection) => ({
        collection,
        rows: byCollection.get(collection.workspace_id) ?? [],
      }));
    const knownCollectionIds = new Set(
      readingCollections.map((collection) => collection.workspace_id),
    );
    for (const [id, rows] of byCollection) {
      if (!knownCollectionIds.has(id)) loose.push(...rows);
    }
    return {
      ungrouped: applyManualOrder(loose, sessionKey, manualOrder ?? []),
      grouped: known,
      masteryGrouped: topics,
      readingGrouped: collections,
    };
  }, [courses, manualOrder, masteryTopics, readingCollections, roots]);

  const ungroupedIds = useMemo(() => ungrouped.map(sessionKey), [ungrouped]);
  const drag = useDragSort({
    ids: ungroupedIds,
    disabled: !onReorder,
    onReorder: (next) => onReorder?.(next),
    scrollRef,
  });

  // One collapse set for every kind of heading — chat, topic, collection,
  // course. Their ids never collide, and a learner folding a heading shut does
  // not care which table it came from. Persisted, so a sidebar arranged once
  // stays arranged across reloads.
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

  if (roots.length === 0) {
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
              : "text-[var(--muted-foreground)] hover:bg-[var(--background)]/40 hover:text-[var(--foreground)]"
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
          ) : (
            <span className="w-3" />
          )}
          <SessionAvatar
            sessionId={session.session_id}
            running={session.status === "running"}
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
          ) : (
            <span
              className={`min-w-0 flex-1 truncate text-[12.5px] ${
                isPlaceholderSessionTitle(session.title)
                  ? "italic opacity-70"
                  : ""
              }`}
              title={session.title}
            >
              {session.title || t("New chat")}
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

  /** A collapsible heading over its conversations. Courses mark themselves
   *  with their colour dot, topics with their emoji; everything else about
   *  the two is the same and stays the same. */
  /** A row wrapped in the drag layer. Only the chat group is arrangeable —
   *  a topic's or a collection's rows are ordered by the surface they belong
   *  to, not by hand. */
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

  const renderGroup = (
    id: string,
    mark: React.ReactNode,
    label: string,
    rows: SessionSummary[],
    sortable = false,
  ) => {
    const collapsed = collapsedCourses.has(id);
    return (
      <div key={id} className="mt-1.5 first:mt-0.5">
        <button
          type="button"
          onClick={() => toggleCourse(id)}
          aria-expanded={!collapsed}
          className="flex w-full min-w-0 items-center gap-1.5 rounded-lg px-1.5 py-1 text-left text-[10.5px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]/75 transition-colors hover:bg-[var(--background)]/40 hover:text-[var(--foreground)]"
        >
          <ChevronRight
            size={11}
            className={`shrink-0 transition-transform ${collapsed ? "" : "rotate-90"}`}
          />
          {mark}
          <span className="min-w-0 flex-1 truncate normal-case">{label}</span>
          <span className="shrink-0 tabular-nums opacity-70">
            {rows.length}
          </span>
        </button>
        {collapsed ? null : (
          <div className="ml-1.5 border-l border-[var(--border)]/50 pl-1">
            {rows.map((session) =>
              sortable ? renderSortableRow(session) : renderRow(session),
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="py-0.5">
      {/* Home conversations get a heading of their own rather than sitting
          loose above the others: chat is one surface among several, and a
          learner scanning for "the thing I was reading" should meet three
          headings of equal weight, not one unlabelled pile and two groups. */}
      {ungrouped.length > 0
        ? renderGroup(
            CHAT_GROUP_ID,
            <House
              aria-hidden
              size={12}
              strokeWidth={1.8}
              className="shrink-0"
            />,
            t("Chat"),
            ungrouped,
            true,
          )
        : null}
      {masteryGrouped.map(({ topic, rows }) =>
        renderGroup(
          topic.path_id,
          <Route
            aria-hidden
            size={12}
            strokeWidth={1.8}
            className="shrink-0"
          />,
          topic.name,
          rows,
        ),
      )}
      {readingGrouped.map(({ collection, rows }) =>
        renderGroup(
          collection.workspace_id,
          <BookText
            aria-hidden
            size={12}
            strokeWidth={1.8}
            className="shrink-0"
          />,
          collection.title,
          rows,
        ),
      )}
      {grouped.map(({ course, rows }) =>
        renderGroup(
          course.id,
          <span
            aria-hidden
            className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: course.color }}
          />,
          course.name,
          rows,
        ),
      )}
    </div>
  );
}

function MenuButton({
  icon: Icon,
  label,
  color,
  checked = false,
  danger = false,
  onClick,
}: {
  icon?: typeof Pencil;
  label: string;
  color?: string;
  checked?: boolean;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-[var(--muted)] ${
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

function sessionKey(session: SessionSummary) {
  return session.session_id;
}

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Archive,
  ArchiveRestore,
  Check,
  ChevronRight,
  GraduationCap,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { SessionAvatar } from "@/components/sidebar/SessionAvatar";
import type { StudyCourse } from "@/lib/courses-api";
import type {
  SessionOrganizationPatch,
  SessionSummary,
} from "@/lib/session-api";
import { organizeSessionTree } from "@/lib/session-organization";
import { isPlaceholderSessionTitle } from "@/lib/session-title";

interface OrganizedSessionListProps {
  sessions: SessionSummary[];
  courses: StudyCourse[];
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
}

interface FloatingMenuPosition {
  left: number;
  top: number;
  maxHeight: number;
  openUpward: boolean;
}

const MENU_WIDTH = 240;
const MENU_GAP = 8;
const VIEWPORT_MARGIN = 12;

function placeMenu(anchor: DOMRect): FloatingMenuPosition {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const preferredHeight = Math.min(380, viewportHeight - VIEWPORT_MARGIN * 2);
  const roomBelow = viewportHeight - anchor.bottom - MENU_GAP - VIEWPORT_MARGIN;
  const roomAbove = anchor.top - MENU_GAP - VIEWPORT_MARGIN;
  const openUpward = roomBelow < preferredHeight && roomAbove > roomBelow;
  const maxHeight = Math.max(
    140,
    Math.min(preferredHeight, openUpward ? roomAbove : roomBelow),
  );

  const roomRight = viewportWidth - anchor.right - MENU_GAP - VIEWPORT_MARGIN;
  const roomLeft = anchor.left - MENU_GAP - VIEWPORT_MARGIN;
  const preferredLeft =
    roomRight >= MENU_WIDTH || roomRight >= roomLeft
      ? anchor.right + MENU_GAP
      : anchor.left - MENU_WIDTH - MENU_GAP;
  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(preferredLeft, viewportWidth - MENU_WIDTH - VIEWPORT_MARGIN),
  );
  const top = openUpward ? anchor.top - MENU_GAP : anchor.bottom + MENU_GAP;

  return { left, top, maxHeight, openUpward };
}

export default function OrganizedSessionList({
  sessions,
  courses,
  activeSessionId,
  emptyLabel,
  nested = true,
  onSelect,
  onRename,
  onDelete,
  onOrganize,
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
            className={child ? "h-3.5 w-3.5 opacity-55" : "opacity-70"}
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
            onClick={(event) => {
              event.stopPropagation();
              if (menuOpen) {
                setOpenMenuId(null);
                setMenuPosition(null);
                return;
              }
              menuAnchorRef.current = event.currentTarget;
              setMenuPosition(
                placeMenu(event.currentTarget.getBoundingClientRect()),
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

  return (
    <div className="py-0.5">{roots.map((session) => renderRow(session))}</div>
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

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Archive,
  BookOpen,
  ClipboardList,
  GraduationCap,
  MessageSquarePlus,
  MoreHorizontal,
  NotebookPen,
  Pencil,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import CourseDialog from "@/components/courses/CourseDialog";
import OrganizedSessionList from "@/components/courses/OrganizedSessionList";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  deleteCourse,
  listCourses,
  updateCourse,
  type StudyCourse,
} from "@/lib/courses-api";
import {
  deleteSession,
  listAllSessions,
  updateSessionOrganization,
  updateSessionTitle,
  type SessionOrganizationPatch,
  type SessionSummary,
} from "@/lib/session-api";

export default function CourseDetailPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const params = useParams<{ courseId: string }>();
  const courseId = String(params.courseId || "");
  const [course, setCourse] = useState<StudyCourse | null>(null);
  const [courses, setCourses] = useState<StudyCourse[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextCourses, nextSessions] = await Promise.all([
        listCourses({ force: true }),
        listAllSessions({ force: true }),
      ]);
      setCourses(nextCourses);
      setCourse(nextCourses.find((item) => item.id === courseId) ?? null);
      setSessions(nextSessions);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    void load();
  }, [load]);

  const courseSessions = useMemo(
    () =>
      sessions.filter((session) => session.preferences?.course_id === courseId),
    [courseId, sessions],
  );
  const activeSessions = useMemo(
    () => courseSessions.filter((session) => !session.preferences?.archived),
    [courseSessions],
  );
  const archivedSessions = useMemo(
    () => courseSessions.filter((session) => session.preferences?.archived),
    [courseSessions],
  );

  const patchSession = useCallback(
    async (sessionId: string, patch: SessionOrganizationPatch) => {
      await updateSessionOrganization(sessionId, patch);
      await load();
    },
    [load],
  );

  const renameSession = useCallback(
    async (sessionId: string, title: string) => {
      await updateSessionTitle(sessionId, title);
      await load();
    },
    [load],
  );

  const removeSession = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Delete this chat?"))) return;
      await deleteSession(sessionId);
      await load();
    },
    [load, t],
  );

  if (loading) {
    return (
      <div className="space-y-4" aria-label={t("Loading course")}>
        <div className="h-10 w-64 animate-pulse rounded bg-[var(--muted)]" />
        <div className="h-48 animate-pulse rounded-2xl bg-[var(--card)]" />
      </div>
    );
  }

  if (!course) {
    return (
      <div className="py-16 text-center">
        <BookOpen className="mx-auto text-[var(--muted-foreground)]" />
        <h1 className="mt-4 font-serif text-xl font-semibold">
          {t("Course not found")}
        </h1>
        <Link
          href="/space"
          className="mt-3 inline-block text-sm text-[var(--primary)]"
        >
          {t("Back to Learning Space")}
        </Link>
      </div>
    );
  }

  const rootCount = activeSessions.filter(
    (session) => !session.preferences?.parent_session_id,
  ).length;

  return (
    <div>
      <header className="relative overflow-visible rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 pl-8">
        <span
          className="absolute inset-y-0 left-0 w-2 rounded-l-2xl"
          style={{ backgroundColor: course.color }}
          aria-hidden
        />
        <div className="flex items-start justify-between gap-5">
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
              {t("Course")}
            </p>
            <h1 className="mt-1 font-serif text-[28px] font-semibold leading-tight tracking-tight text-[var(--foreground)]">
              {course.name}
            </h1>
            <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-[var(--muted-foreground)]">
              {course.description || t("A focused home for this subject.")}
            </p>
            <p className="mt-3 text-[11px] text-[var(--muted-foreground)]/75">
              {t("{{count}} active conversations", { count: rootCount })}
            </p>
          </div>
          <div className="relative flex shrink-0 items-center gap-2">
            <Link
              href={`/home?course=${encodeURIComponent(course.id)}`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-2 text-[12px] font-medium text-[var(--background)] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              <MessageSquarePlus size={14} />
              {t("New course chat")}
            </Link>
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              className="rounded-lg border border-[var(--border)] p-2 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              aria-label={t("Course actions")}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <MoreHorizontal size={15} />
            </button>
            {menuOpen ? (
              <div className="absolute right-0 top-10 z-20 w-40 rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1.5 text-[12px] shadow-xl">
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setEditOpen(true);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-[var(--muted)]"
                >
                  <Pencil size={13} /> {t("Edit course")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setDeleteOpen(true);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[var(--destructive)] hover:bg-[var(--muted)]"
                >
                  <Trash2 size={13} /> {t("Delete course")}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Shortcut href="/notebook" icon={NotebookPen} label={t("Notebooks")} />
        <Shortcut
          href="/space/questions"
          icon={ClipboardList}
          label={t("Question Bank")}
        />
        <Shortcut
          href="/space/learning"
          icon={GraduationCap}
          label={t("Mastery Path")}
        />
      </div>

      <section className="mt-7 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-3">
        <div className="flex items-center justify-between px-2 pb-2">
          <div>
            <h2 className="font-serif text-[17px] font-semibold">
              {t("Conversations")}
            </h2>
            <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
              {t(
                "Tutor threads stay nested under the conversation they came from.",
              )}
            </p>
          </div>
        </div>
        <OrganizedSessionList
          sessions={activeSessions}
          courses={courses}
          activeSessionId={null}
          emptyLabel={t("No conversations in this course")}
          onSelect={(sessionId) => router.push(`/home/${sessionId}`)}
          onRename={renameSession}
          onDelete={removeSession}
          onOrganize={patchSession}
        />
      </section>

      {archivedSessions.length > 0 ? (
        <details className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-3">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-2 py-1 text-[13px] font-medium">
            <Archive size={14} />
            {t("Archived conversations")}
            <span className="text-[11px] font-normal text-[var(--muted-foreground)]">
              {archivedSessions.length}
            </span>
          </summary>
          <OrganizedSessionList
            sessions={archivedSessions}
            courses={courses}
            activeSessionId={null}
            onSelect={(sessionId) => router.push(`/home/${sessionId}`)}
            onRename={renameSession}
            onDelete={removeSession}
            onOrganize={patchSession}
          />
        </details>
      ) : null}

      <CourseDialog
        open={editOpen}
        course={course}
        onClose={() => setEditOpen(false)}
        onSave={async (input) => {
          const updated = await updateCourse(course.id, input);
          setCourse(updated);
          setCourses((previous) =>
            previous.map((item) => (item.id === updated.id ? updated : item)),
          );
        }}
      />
      <ConfirmDialog
        open={deleteOpen}
        title={t("Delete course?")}
        confirmLabel={t("Delete course")}
        tone="danger"
        onCancel={() => setDeleteOpen(false)}
        onConfirm={() => {
          void deleteCourse(course.id).then(() => router.push("/space"));
        }}
      >
        {t(
          "Conversations will not be deleted. They will move to Unclassified.",
        )}
      </ConfirmDialog>
    </div>
  );
}

function Shortcut({
  href,
  icon: Icon,
  label,
}: {
  href: string;
  icon: typeof NotebookPen;
  label: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--foreground)]/20 hover:text-[var(--foreground)]"
    >
      <Icon size={15} strokeWidth={1.7} />
      {label}
    </Link>
  );
}

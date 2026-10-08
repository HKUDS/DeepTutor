"use client";

import { PageHeader, pageActionClass, pageGridClass } from '@/components/layout/FeaturePage'
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Archive,
  ArrowLeft,
  BookOpen,
  MessageSquarePlus,
  MoreHorizontal,
  Pencil,
  Signpost,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import CourseConventions from "@/components/courses/CourseConventions";
import CourseDialog from "@/components/courses/CourseDialog";
import CourseNextStep from "@/components/courses/CourseNextStep";
import CourseProgress from "@/components/courses/CourseProgress";
import CourseResources from "@/components/courses/CourseResources";
import CourseSyllabus from "@/components/courses/CourseSyllabus";
import OrganizedSessionList from "@/components/courses/OrganizedSessionList";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  attachCourseResource,
  deleteCourse,
  detachCourseResource,
  getCourseState,
  listCourses,
  setCourseSyllabus,
  setSyllabusUnitCovered,
  updateCourse,
  type CourseResourceKind,
  type CourseState,
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
  const [state, setState] = useState<CourseState | null>(null);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextCourses, nextSessions, nextState] = await Promise.all([
        listCourses({ force: true }),
        listAllSessions({ force: true }),
        // The aggregate reaches across five subsystems, so one of them being
        // unavailable must not take the page with it — the tiles below render
        // their own empty state from a null.
        getCourseState(courseId, { force: true }).catch(() => null),
      ]);
      setCourses(nextCourses);
      setCourse(nextCourses.find((item) => item.id === courseId) ?? null);
      setSessions(nextSessions);
      setState(nextState);
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

  const attachResource = useCallback(
    async (input: {
      kind: CourseResourceKind;
      ref_id: string;
      label: string;
    }) => {
      await attachCourseResource(courseId, input);
      await load();
    },
    [courseId, load],
  );

  const detachResource = useCallback(
    async (resourceId: string) => {
      await detachCourseResource(courseId, resourceId);
      await load();
    },
    [courseId, load],
  );

  const saveInstructions = useCallback(
    async (instructions: string) => {
      const updated = await updateCourse(courseId, { instructions });
      setCourse(updated);
    },
    [courseId],
  );

  const saveSyllabus = useCallback(
    async (units: { id?: string; title: string; topics: string[] }[]) => {
      await setCourseSyllabus(courseId, units);
      await load();
    },
    [courseId, load],
  );

  const toggleUnit = useCallback(
    async (unitId: string, covered: boolean) => {
      await setSyllabusUnitCovered(courseId, unitId, covered);
      await load();
    },
    [courseId, load],
  );

  const setArchived = useCallback(
    async (archived: boolean) => {
      const updated = await updateCourse(courseId, {
        status: archived ? "archived" : "active",
      });
      setCourse(updated);
    },
    [courseId],
  );

  const removeSession = useCallback(
    async (sessionId: string) => {
      if (!window.confirm(t("Permanently delete this chat and its tutor threads? This cannot be undone."))) return;
      await deleteSession(sessionId);
      await load();
    },
    [load, t],
  );

  const confirmDelete = useCallback(async () => {
    if (!course) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await deleteCourse(course.id);
      router.push("/courses");
    } catch (error) {
      setDeleteError(
        error instanceof Error && error.message
          ? error.message
          : t("Delete failed"),
      );
    } finally {
      setDeleteBusy(false);
    }
  }, [course, router, t]);

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
          href="/courses"
          className="mt-3 inline-block text-sm text-[var(--primary)]"
        >
          {t("Back to Courses")}
        </Link>
      </div>
    );
  }

  const rootCount = activeSessions.filter(
    (session) => !session.preferences?.parent_session_id,
  ).length;

  return (
    <div>
      <div className="mb-5">
        <Link
          href="/courses"
          className="group inline-flex items-center gap-1.5 text-[13px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          <ArrowLeft
            size={15}
            strokeWidth={1.8}
            className="transition-transform group-hover:-translate-x-0.5"
          />
          {t("Courses")}
        </Link>
      </div>
      <PageHeader
        title={course.name}
        description={course.description || t("A focused home for this subject.")}
        meta={course.status === "archived" ? <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]">{t("Archived")}</span> : null}
        action={
          <div className="relative flex shrink-0 items-center gap-2">
            <Link
              href={`/chat?course=${encodeURIComponent(course.id)}&capability=course_study`}
              className={pageActionClass()}
            >
              <Signpost size={14} />
              {t("Start course study")}
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
                <Link
                  // Carries the course's declared starting mode, so "a new chat
                  // in this course" opens the way this course is studied rather
                  // than in whatever mode the composer was last left in.
                  href={`/chat?course=${encodeURIComponent(course.id)}${
                    course.default_capability
                      ? `&capability=${encodeURIComponent(course.default_capability)}`
                      : ""
                  }`}
                  onClick={() => setMenuOpen(false)}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-[var(--muted)]"
                >
                  <MessageSquarePlus size={13} /> {t("New course chat")}
                </Link>
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
                    void setArchived(course.status !== "archived");
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-[var(--muted)]"
                >
                  <Archive size={13} />{" "}
                  {course.status === "archived"
                    ? t("Restore course")
                    : t("Archive course")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setDeleteError(null);
                    setDeleteOpen(true);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[var(--destructive)] hover:bg-[var(--muted)]"
                >
                  <Trash2 size={13} /> {t("Delete course")}
                </button>
              </div>
            ) : null}
          </div>
        }
      />
      <p className="-mt-3 mb-6 text-[11px] text-[var(--muted-foreground)]">
        {t("{{count}} active conversations", { count: rootCount })}
      </p>

      <div className="mt-4">
        <CourseNextStep state={state} courseId={courseId} />
      </div>

      <div className="mt-4">
        <CourseProgress state={state} courseId={courseId} />
      </div>

      <div className="mt-4">
        <CourseSyllabus
          state={state}
          onSave={saveSyllabus}
          onToggle={toggleUnit}
        />
      </div>

      <div className={`mt-4 ${pageGridClass(2)}`}>
        <CourseResources
          courseId={course.id}
          resources={state?.resources ?? []}
          onAttach={attachResource}
          onDetach={detachResource}
        />
        <CourseConventions
          instructions={course.instructions}
          agentNotes={course.agent_notes}
          onSave={saveInstructions}
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
          onSelect={(sessionId) => router.push(`/chat/${sessionId}`)}
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
            onSelect={(sessionId) => router.push(`/chat/${sessionId}`)}
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
        busy={deleteBusy}
        busyLabel={t("Deleting…")}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={confirmDelete}
      >
        {t(
          "Conversations will not be deleted. They will move to Unclassified.",
        )}
        {deleteError ? (
          <p role="alert" className="mt-2 text-[var(--destructive)]">
            {deleteError}
          </p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

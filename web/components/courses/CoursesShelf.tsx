"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Archive,
  ArrowRight,
  BookOpen,
  CircleAlert,
  Layers,
  MessagesSquare,
  Plus,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import CourseDialog from "@/components/courses/CourseDialog";
import { createCourse, listCourses, type StudyCourse } from "@/lib/courses-api";
import { formatRelativeTime } from "@/lib/relative-time";
import { listAllSessions, type SessionSummary } from "@/lib/session-api";

/**
 * The course library — every subject the learner is carrying.
 *
 * Each card reports what the course actually holds rather than only its name.
 * A course with nothing attached is the one thing worth noticing from here, and
 * a shelf of identical name-only tiles hides exactly that. The counts come from
 * data this page already has (the course's own reference set, plus the session
 * list), so the shelf costs two requests no matter how many courses there are —
 * the deeper per-course state lives one click in, where it is one aggregate
 * instead of N.
 *
 * The last cell is always "new course". Keeping the only entry point inside the
 * grid lets it grow with the shelf instead of stranding an empty right-hand
 * third beside a lone toolbar button.
 */
export default function CoursesShelf() {
  const { t, i18n } = useTranslation();
  const [courses, setCourses] = useState<StudyCourse[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      listCourses({ force: true }),
      listAllSessions({ force: true }),
    ])
      .then(([nextCourses, nextSessions]) => {
        if (cancelled) return;
        setCourses(nextCourses);
        setSessions(nextSessions);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : "");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // A finished term should stop competing for attention without disappearing —
  // its material, questions and paths are all still there.
  const [active, archived] = useMemo(() => {
    const live: StudyCourse[] = [];
    const putAway: StudyCourse[] = [];
    for (const course of courses) {
      (course.status === "archived" ? putAway : live).push(course);
    }
    return [live, putAway] as const;
  }, [courses]);

  const counts = useMemo(() => {
    const result = new Map<string, number>();
    for (const session of sessions) {
      if (
        session.preferences?.archived ||
        session.preferences?.parent_session_id
      )
        continue;
      const courseId = session.preferences?.course_id;
      if (courseId) result.set(courseId, (result.get(courseId) ?? 0) + 1);
    }
    return result;
  }, [sessions]);

  // When each course was last touched. A shelf is read to decide what to pick
  // up, and "three days ago" answers that faster than any count.
  const lastActive = useMemo(() => {
    const result = new Map<string, number>();
    for (const session of sessions) {
      const courseId = session.preferences?.course_id;
      if (!courseId) continue;
      const at = Number(session.updated_at ?? 0);
      if (at > (result.get(courseId) ?? 0)) result.set(courseId, at);
    }
    return result;
  }, [sessions]);

  const saveCourse = useCallback(
    async (input: {
      name: string;
      description: string;
      color: string;
      default_capability: string;
      default_persona: string;
    }) => {
      const course = await createCourse(input);
      setCourses((previous) => [...previous, course]);
    },
    [],
  );

  return (
    <section aria-labelledby="courses-shelf-title">
      <div className="mb-4">
        <h1
          id="courses-shelf-title"
          className="font-serif text-[22px] font-semibold tracking-tight text-[var(--foreground)]"
        >
          {t("My courses")}
        </h1>
        <p className="mt-1 text-[12.5px] text-[var(--muted-foreground)]">
          {t(
            "One subject's material, paths, notes and conversations, all in one place.",
          )}
        </p>
      </div>

      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((item) => (
            <div
              key={item}
              className="h-32 animate-pulse rounded-xl border border-[var(--border)] bg-[var(--card)]"
            />
          ))}
        </div>
      ) : loadError !== null ? (
        <div
          role="alert"
          className="flex min-h-32 items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 text-[12.5px] text-[var(--muted-foreground)]"
        >
          <CircleAlert size={16} strokeWidth={1.8} aria-hidden />
          <span>
            <span className="block font-medium text-[var(--foreground)]">
              {t("Courses could not load")}
            </span>
            <span className="mt-1 block leading-relaxed">
              {loadError || t("Courses could not load")}
            </span>
          </span>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {active.map((course) => (
            <Link
              key={course.id}
              href={`/courses/${course.id}`}
              className="group flex min-h-32 flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 hover:shadow-[0_6px_20px_-12px_rgba(0,0,0,0.25)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              <div className="flex items-start justify-between gap-3">
                <h3 className="flex min-w-0 items-center gap-2 font-serif text-[16px] font-semibold text-[var(--foreground)]">
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ backgroundColor: course.color }}
                  />
                  <span className="truncate">{course.name}</span>
                </h3>
                <ArrowRight
                  size={15}
                  className="mt-0.5 shrink-0 text-[var(--muted-foreground)]/45 transition-transform group-hover:translate-x-0.5"
                />
              </div>
              <p className="mt-1 line-clamp-2 flex-1 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                {course.description || t("A focused home for this subject.")}
              </p>
              {course.resources.length === 0 ? (
                <p className="mt-3 text-[10.5px] text-[var(--muted-foreground)]/75">
                  {t("Nothing attached yet")}
                </p>
              ) : (
                <div className="mt-3 flex items-center gap-3 text-[10.5px] text-[var(--muted-foreground)]/75">
                  <span
                    className="inline-flex items-center gap-1"
                    title={t("Materials")}
                  >
                    <Layers size={11} strokeWidth={1.8} />
                    {course.resources.length}
                  </span>
                  <span
                    className="inline-flex items-center gap-1"
                    title={t("Conversations")}
                  >
                    <MessagesSquare size={11} strokeWidth={1.8} />
                    {counts.get(course.id) ?? 0}
                  </span>
                  {lastActive.has(course.id) ? (
                    <span className="ml-auto">
                      {formatRelativeTime(
                        lastActive.get(course.id) ?? 0,
                        i18n.language,
                      )}
                    </span>
                  ) : null}
                </div>
              )}
            </Link>
          ))}

          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="group flex min-h-32 flex-col items-start justify-center gap-2 rounded-xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 p-4 text-left transition-colors hover:border-[var(--foreground)]/25 hover:bg-[var(--card)]"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]">
              {courses.length === 0 ? (
                <BookOpen size={14} strokeWidth={1.7} />
              ) : (
                <Plus size={14} strokeWidth={1.8} />
              )}
            </span>
            <span className="text-[13px] font-medium text-[var(--foreground)]">
              {courses.length === 0
                ? t("Create your first course")
                : t("New course")}
            </span>
            <span className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {courses.length === 0
                ? t(
                    "Start with a subject such as Operating Systems or Network Security.",
                  )
                : t("Attach its textbook, then let DeepTutor plan from there.")}
            </span>
          </button>
        </div>
      )}

      {archived.length > 0 ? (
        <details className="mt-4">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]">
            <Archive size={13} strokeWidth={1.7} />
            {t("Archived courses")}
            <span className="text-[11px] text-[var(--muted-foreground)]/70">
              {archived.length}
            </span>
          </summary>
          <ul className="mt-2 space-y-0.5">
            {archived.map((course) => (
              <li key={course.id}>
                <Link
                  href={`/courses/${course.id}`}
                  className="flex items-baseline gap-2 rounded-lg px-2.5 py-1.5 transition-colors hover:bg-[var(--muted)]/40"
                >
                  <span
                    className="h-1.5 w-1.5 shrink-0 self-center rounded-full opacity-60"
                    style={{ backgroundColor: course.color }}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-[var(--muted-foreground)]">
                    {course.name}
                  </span>
                  {course.archived_at > 0 ? (
                    <span className="shrink-0 text-[10.5px] text-[var(--muted-foreground)]/70">
                      {formatRelativeTime(course.archived_at, i18n.language)}
                    </span>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <CourseDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={saveCourse}
      />
    </section>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, BookOpen, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import CourseDialog from "@/components/courses/CourseDialog";
import { createCourse, listCourses, type StudyCourse } from "@/lib/courses-api";
import { listAllSessions, type SessionSummary } from "@/lib/session-api";

export default function CoursesShelf() {
  const { t } = useTranslation();
  const [courses, setCourses] = useState<StudyCourse[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
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
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const saveCourse = useCallback(
    async (input: { name: string; description: string; color: string }) => {
      const course = await createCourse(input);
      setCourses((previous) => [...previous, course]);
    },
    [],
  );

  return (
    <section className="mb-9" aria-labelledby="courses-shelf-title">
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <h2
            id="courses-shelf-title"
            className="font-serif text-[18px] font-semibold tracking-tight text-[var(--foreground)]"
          >
            {t("My courses")}
          </h2>
          <p className="mt-1 text-[12.5px] text-[var(--muted-foreground)]">
            {t(
              "Keep each subject's conversations together without mixing their context.",
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/25 hover:bg-[var(--muted)]/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          <Plus size={14} />
          {t("New course")}
        </button>
      </div>

      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((item) => (
            <div
              key={item}
              className="h-28 animate-pulse rounded-xl border border-[var(--border)] bg-[var(--card)]"
            />
          ))}
        </div>
      ) : courses.length === 0 ? (
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className="group flex w-full items-center gap-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--card)]/55 p-5 text-left transition-colors hover:border-[var(--foreground)]/25 hover:bg-[var(--card)]"
        >
          <span className="flex h-11 w-9 items-center justify-center rounded-r-md border border-l-4 border-[var(--border)] border-l-[#C65D2E] bg-[var(--background)]">
            <BookOpen size={17} strokeWidth={1.6} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[14px] font-medium text-[var(--foreground)]">
              {t("Create your first course")}
            </span>
            <span className="mt-1 block text-[12px] text-[var(--muted-foreground)]">
              {t(
                "Start with a subject such as Operating Systems or Network Security.",
              )}
            </span>
          </span>
          <ArrowRight size={16} className="text-[var(--muted-foreground)]" />
        </button>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((course) => (
            <Link
              key={course.id}
              href={`/space/courses/${course.id}`}
              className="group relative min-h-28 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 pl-5 transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 hover:shadow-[0_6px_20px_-12px_rgba(0,0,0,0.25)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              <span
                aria-hidden
                className="absolute inset-y-0 left-0 w-1.5"
                style={{ backgroundColor: course.color }}
              />
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate font-serif text-[16px] font-semibold text-[var(--foreground)]">
                    {course.name}
                  </h3>
                  <p className="mt-1 line-clamp-2 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                    {course.description ||
                      t("A focused home for this subject.")}
                  </p>
                </div>
                <ArrowRight
                  size={15}
                  className="mt-0.5 shrink-0 text-[var(--muted-foreground)]/45 transition-transform group-hover:translate-x-0.5"
                />
              </div>
              <div className="mt-3 text-[10.5px] text-[var(--muted-foreground)]/75">
                {t("{{count}} conversations", {
                  count: counts.get(course.id) ?? 0,
                })}
              </div>
            </Link>
          ))}
        </div>
      )}

      <CourseDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={saveCourse}
      />
    </section>
  );
}

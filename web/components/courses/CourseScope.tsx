"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { School, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  attachCourseResource,
  listCourses,
  type CourseResourceKind,
  type StudyCourse,
} from "@/lib/courses-api";

/**
 * Arriving at a learning surface "inside" a course.
 *
 * A course references a knowledge base, a path, a workspace, a notebook — but
 * every one of those is made on its own surface, so without this the container
 * only ever fills up by the learner remembering to walk back and attach what
 * they just built. That is the step nobody performs, and it is why an
 * enthusiastic first week leaves a course page still reading "nothing attached
 * yet" while four paths and two workspaces exist elsewhere.
 *
 * So a surface opened as `?course=<id>` does two things: it says which course
 * it is standing in, and it attaches whatever gets created there back to it.
 * The `?course=` link is the whole contract — no surface needs to know what a
 * course *is* beyond that.
 */

export interface CourseScope {
  id: string;
  /** Resolved course, or null while loading / if it could not be read. */
  course: StudyCourse | null;
  /** Reference ids this course already holds of one kind. */
  refIds: (kind: CourseResourceKind) => string[];
  /**
   * Attach something just created here. Safe to call unconditionally — with no
   * course in the URL it does nothing, so callers need no branch of their own.
   */
  attach: (
    kind: CourseResourceKind,
    refId: string,
    label: string,
  ) => Promise<void>;
}

/** Read `?course=<id>` and resolve it. Returns null when the URL carries none. */
export function useCourseScope(): CourseScope | null {
  const courseId = useSearchParams().get("course")?.trim() ?? "";
  const [course, setCourse] = useState<StudyCourse | null>(null);
  // Re-read after an attach so a second creation in the same visit sees the
  // first one already in the course.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!courseId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCourse(null);
      return;
    }
    let cancelled = false;
    void listCourses()
      .then((courses) => {
        if (!cancelled) {
          setCourse(courses.find((item) => item.id === courseId) ?? null);
        }
      })
      .catch(() => {
        // Unresolved: the chip falls back to "this course" and attaching still
        // works, because attaching only needs the id.
        if (!cancelled) setCourse(null);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, version]);

  const refIds = useCallback(
    (kind: CourseResourceKind) =>
      (course?.resources ?? [])
        .filter((resource) => resource.kind === kind)
        .map((resource) => resource.ref_id),
    [course],
  );

  const attach = useCallback(
    async (kind: CourseResourceKind, refId: string, label: string) => {
      if (!courseId || !refId) return;
      try {
        await attachCourseResource(courseId, {
          kind,
          ref_id: refId,
          label,
        });
        setVersion((current) => current + 1);
      } catch {
        // Attaching is a courtesy on top of a creation that already succeeded.
        // Failing it must not take down the thing the learner actually asked
        // for; the course page's own picker remains the way to fix it up.
      }
    },
    [courseId],
  );

  if (!courseId) return null;
  return { id: courseId, course, refIds, attach };
}

/**
 * The "you are inside this course" chip.
 *
 * Same shape on every surface on purpose: once a learner has seen it in the
 * question bank, it means the same thing in the reader and the atlas — this
 * list is narrowed, and here is the way out.
 */
export function CourseScopeChip({ scope }: { scope: CourseScope }) {
  const { t } = useTranslation();
  const router = useRouter();
  const pathname = usePathname();

  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--card)] py-0.5 pl-2 pr-1 text-[10.5px] font-medium text-[var(--muted-foreground)]">
      <Link
        href={`/courses/${scope.id}`}
        className="inline-flex items-center gap-1 transition-colors hover:text-[var(--foreground)]"
      >
        <School size={11} strokeWidth={1.8} />
        {scope.course?.name || t("This course")}
      </Link>
      <button
        type="button"
        onClick={() => router.replace(pathname)}
        aria-label={t("Show every course")}
        className="rounded-full p-0.5 transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      >
        <X size={11} />
      </button>
    </span>
  );
}

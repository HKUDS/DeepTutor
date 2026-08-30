"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, ChevronDown, School } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { StudyCourse } from "@/lib/courses-api";

/**
 * Which course this conversation belongs to — shown, and changeable, in the
 * composer.
 *
 * Course Study was reachable two ways and worked in only one of them. Opening a
 * course and pressing "Start course study" bound the course through a query
 * parameter; picking Course Study from this menu bound nothing, and produced a
 * conversation that looked identical to the one that worked. The mode then had
 * no course to sense and no way to be given one, so it advised the learner to
 * press a button that did not exist.
 *
 * Both halves of that are this control. It *shows* the binding, so a learner
 * can tell a working Course Study session from an inert one without sending a
 * message to find out; and it *is* the binding, so choosing the mode and
 * choosing the course happen in the same place instead of one of them happening
 * on a different page.
 *
 * Visible whenever it has something to say: in Course Study always (the mode is
 * inert without it), and otherwise only once a course is attached — an ordinary
 * chat gains a pill only if it belongs somewhere, never an empty one asking to
 * be filled.
 */

export function CoursePill({
  courses,
  courseId,
  onSelect,
  needsCourse,
  compact = false,
}: {
  courses: StudyCourse[];
  courseId: string;
  onSelect: (courseId: string) => void;
  /** True in Course Study, where an unbound conversation cannot do anything. */
  needsCourse: boolean;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        !menuRef.current?.contains(target) &&
        !buttonRef.current?.contains(target)
      ) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const active = courses.find((course) => course.id === courseId) ?? null;
  // An archived course keeps its conversations; it just stops being offered for
  // new ones. Still listed while it is the current binding, or the pill would
  // name a course the menu claims does not exist.
  const selectable = courses.filter(
    (course) => course.status !== "archived" || course.id === courseId,
  );

  if (!needsCourse && !courseId) return null;

  // Unbound inside Course Study is not a neutral state — it is the one where
  // nothing works — so it reads as an unfinished field rather than a quiet
  // label. Bound, it goes as quiet as the mode chip beside it.
  const unbound = !courseId;

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2 text-[13px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
          unbound
            ? "text-[var(--primary)] hover:bg-[var(--primary)]/10"
            : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
        }`}
      >
        {active?.color ? (
          <span
            aria-hidden
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: active.color }}
          />
        ) : (
          <School size={15} strokeWidth={1.7} className="shrink-0" />
        )}
        {compact && !unbound ? null : (
          <span className="max-w-[150px] truncate">
            {active?.name ?? t("Pick a course")}
          </span>
        )}
        <ChevronDown
          size={12}
          strokeWidth={2}
          className={`-mr-0.5 shrink-0 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          className="dt-popup-up absolute bottom-full left-0 z-50 mb-1.5 w-[248px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-lg backdrop-blur-md"
        >
          <div className="max-h-[280px] overflow-y-auto">
            {selectable.length === 0 ? (
              <p className="px-3 py-2.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                {t("No courses yet — make one to group a subject's material.")}
              </p>
            ) : (
              selectable.map((course) => (
                <button
                  key={course.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={course.id === courseId}
                  onClick={() => {
                    onSelect(course.id);
                    setOpen(false);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/60"
                >
                  <span
                    aria-hidden
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: course.color }}
                  />
                  <span className="min-w-0 flex-1 truncate">{course.name}</span>
                  {course.id === courseId ? (
                    <Check size={12} className="shrink-0" />
                  ) : null}
                </button>
              ))
            )}
          </div>

          {courseId ? (
            <button
              type="button"
              onClick={() => {
                onSelect("");
                setOpen(false);
              }}
              className="mt-1 flex w-full items-center gap-2 border-t border-[var(--border)]/70 px-3 py-1.5 pt-2 text-left text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
            >
              {t("Not in a course")}
            </button>
          ) : null}

          <Link
            href="/courses"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2 border-t border-[var(--border)]/70 px-3 py-1.5 pt-2 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
          >
            {t("Manage courses")}
          </Link>
        </div>
      )}
    </div>
  );
}

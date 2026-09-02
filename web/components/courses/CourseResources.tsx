"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  Bot,
  Database,
  GraduationCap,
  NotebookPen,
  Plus,
  ScrollText,
  Users,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  listCourseResourceCandidates,
  type CourseResourceCandidates,
  type CourseResourceKind,
  type CourseResourceState,
} from "@/lib/courses-api";

/**
 * What this course studies with.
 *
 * A course references resources rather than owning them, so this list is a set
 * of pointers: detaching one here never destroys the knowledge base, book, or
 * path it pointed at, and the same textbook may legitimately appear under two
 * courses. A pointer whose target has since disappeared is shown as unavailable
 * rather than dropped — a row that silently vanishes leaves the learner
 * wondering what happened to their material.
 */

const KIND_ICONS: Record<CourseResourceKind, typeof BookOpen> = {
  knowledge_base: Database,
  book: BookOpen,
  notebook: NotebookPen,
  mastery_path: GraduationCap,
  reading_workspace: ScrollText,
  partner: Bot,
  partner_group: Users,
};

function useKindNames(): Record<CourseResourceKind, string> {
  const { t } = useTranslation();
  return {
    knowledge_base: t("Knowledge base"),
    book: t("Book"),
    notebook: t("Notebook"),
    mastery_path: t("Mastery path"),
    reading_workspace: t("Reading"),
    partner: t("Partner"),
    partner_group: t("Partner group"),
  };
}

/**
 * Ways to bring something new into a course, rather than only reference what
 * already exists.
 *
 * A brand-new course used to offer nothing but an empty picker: every tile told
 * the learner to attach a path or a workspace, and the only place to make one
 * was a surface that did not know the course existed — so whatever they built
 * there stayed there. Each of these carries `?course=`, which those surfaces now
 * read: the thing created arrives already attached.
 */
const CREATE_ROUTES: {
  kind: CourseResourceKind;
  href: (courseId: string) => string;
  label: string;
}[] = [
  {
    kind: "knowledge_base",
    href: () => "/knowledge-bases",
    label: "New knowledge base",
  },
  {
    kind: "mastery_path",
    href: (courseId) => `/mastery?course=${encodeURIComponent(courseId)}`,
    label: "New mastery path",
  },
  {
    kind: "reading_workspace",
    href: (courseId) => `/reading?course=${encodeURIComponent(courseId)}`,
    label: "New reading collection",
  },
  {
    kind: "notebook",
    href: (courseId) => `/notebooks?course=${encodeURIComponent(courseId)}`,
    label: "New notebook",
  },
];

export default function CourseResources({
  courseId,
  resources,
  onAttach,
  onDetach,
}: {
  courseId: string;
  resources: CourseResourceState[];
  onAttach: (input: {
    kind: CourseResourceKind;
    ref_id: string;
    label: string;
  }) => Promise<void>;
  onDetach: (resourceId: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const kindNames = useKindNames();
  const [picking, setPicking] = useState(false);
  const [candidates, setCandidates] = useState<CourseResourceCandidates>({});
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [busy, setBusy] = useState("");

  const loadCandidates = useCallback(async () => {
    setLoadingCandidates(true);
    try {
      setCandidates(await listCourseResourceCandidates({ force: true }));
    } catch {
      // The picker is an addition, not the page: if the catalogue cannot be
      // read the attached list above still renders.
      setCandidates({});
    } finally {
      setLoadingCandidates(false);
    }
  }, []);

  useEffect(() => {
    if (picking) void loadCandidates();
  }, [loadCandidates, picking]);

  // The catalogue always answers with every kind, each holding a (often empty)
  // list — so counting keys never reaches zero and the empty state never
  // showed. What matters is whether anything at all is attachable.
  const candidateCount = Object.values(candidates).reduce(
    (sum, rows) => sum + (rows?.length ?? 0),
    0,
  );

  const attached = new Set(
    resources.map((resource) => `${resource.kind}:${resource.ref_id}`),
  );

  const attach = async (
    kind: CourseResourceKind,
    refId: string,
    label: string,
  ) => {
    setBusy(`${kind}:${refId}`);
    try {
      await onAttach({ kind, ref_id: refId, label });
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-serif text-[16px] font-semibold text-[var(--foreground)]">
            {t("Materials")}
          </h2>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Everything this course studies with. Conversations here start with these already in hand.",
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setPicking((open) => !open)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50"
        >
          <Plus size={13} />
          {t("Add")}
        </button>
      </div>

      {resources.length === 0 ? (
        <p className="mt-3 rounded-xl border border-dashed border-[var(--border)] px-3 py-4 text-center text-[11.5px] text-[var(--muted-foreground)]">
          {t(
            "Nothing attached yet. Add a textbook or knowledge base and this course starts knowing what it is about.",
          )}
        </p>
      ) : (
        <ul className="mt-3 space-y-1">
          {resources.map((resource) => {
            const Icon = KIND_ICONS[resource.kind];
            return (
              <li
                key={resource.id}
                className="group flex items-center gap-2.5 rounded-xl px-2.5 py-2 transition-colors hover:bg-[var(--muted)]/40"
              >
                <Icon
                  size={14}
                  strokeWidth={1.7}
                  className="shrink-0 text-[var(--muted-foreground)]"
                />
                <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
                  <span className="truncate text-[12.5px] text-[var(--foreground)]">
                    {resource.label}
                  </span>
                  {/* Grouped with the label rather than given its own column:
                      as a separate cell its varying width pushed the kind name
                      to a different x-position on every row. */}
                  {!resource.available ? (
                    <span
                      className="shrink-0 cursor-help text-[10.5px] text-[var(--muted-foreground)]/80"
                      title={t(
                        "This target no longer exists — remove the reference, or attach the resource again.",
                      )}
                    >
                      · {t("Unavailable")}
                    </span>
                  ) : null}
                </span>
                <span className="shrink-0 text-[10.5px] text-[var(--muted-foreground)]/70">
                  {kindNames[resource.kind]}
                </span>
                <button
                  type="button"
                  onClick={() => void onDetach(resource.id)}
                  aria-label={t("Remove from course")}
                  className="shrink-0 rounded-md p-1 text-[var(--muted-foreground)] opacity-0 transition-opacity hover:text-[var(--destructive)] focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <X size={13} />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {picking ? (
        <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          {loadingCandidates ? (
            <p className="text-[11.5px] text-[var(--muted-foreground)]">
              {t("Loading")}
            </p>
          ) : (
            <div className="space-y-3">
              {candidateCount === 0 ? (
                <p className="text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                  {t(
                    "Nothing made yet to attach. Start one below and it joins this course as soon as it exists.",
                  )}
                </p>
              ) : null}
              {(Object.keys(candidates) as CourseResourceKind[]).map((kind) => {
                const rows = candidates[kind] ?? [];
                if (rows.length === 0) return null;
                return (
                  <div key={kind}>
                    <p className="text-[10.5px] text-[var(--muted-foreground)]/80">
                      {kindNames[kind] ?? kind}
                    </p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {rows.map((row) => {
                        const key = `${kind}:${row.ref_id}`;
                        const already = attached.has(key);
                        return (
                          <button
                            key={key}
                            type="button"
                            disabled={already || busy === key}
                            onClick={() =>
                              void attach(kind, row.ref_id, row.label)
                            }
                            className="max-w-[220px] truncate rounded-lg border border-[var(--border)] px-2 py-1 text-[11.5px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50 disabled:opacity-40"
                          >
                            {already ? `✓ ${row.label}` : row.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}

              <div className="border-t border-[var(--border)]/70 pt-3">
                <p className="text-[10.5px] text-[var(--muted-foreground)]/80">
                  {t("Start something new")}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {CREATE_ROUTES.map((route) => {
                    const Icon = KIND_ICONS[route.kind];
                    return (
                      <Link
                        key={route.kind}
                        href={route.href(courseId)}
                        className="inline-flex max-w-[220px] items-center gap-1.5 rounded-lg border border-dashed border-[var(--border)] px-2 py-1 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)]"
                      >
                        <Icon
                          size={12}
                          strokeWidth={1.7}
                          className="shrink-0"
                        />
                        <span className="truncate">{t(route.label)}</span>
                      </Link>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

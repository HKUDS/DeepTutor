"use client";

import Link from "next/link";
import {
  ClipboardList,
  GraduationCap,
  NotebookPen,
  ScrollText,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CourseState } from "@/lib/courses-api";

/**
 * Where this course stands, as four entry points that carry their own numbers.
 *
 * These replaced four bare shortcuts that linked to the global notebook,
 * question bank, and mastery-path surfaces with no course scope at all — the
 * page promised "this course's three things" and delivered site-wide
 * navigation. Every figure below comes from `GET /api/courses/{id}/state`,
 * which counts only what this course references or produced, and every link
 * carries the course through so the destination can scope itself too.
 *
 * A section with nothing in it still renders, saying what would put something
 * there. A tile that disappears when empty takes the way to fix that with it.
 */
export default function CourseProgress({
  state,
  courseId,
}: {
  state: CourseState | null;
  courseId: string;
}) {
  const { t } = useTranslation();
  const course = encodeURIComponent(courseId);

  const paths = state?.mastery.paths ?? [];
  const objectivesMastered = paths.reduce(
    (sum, path) => sum + path.objectives_mastered,
    0,
  );
  const objectivesTotal = paths.reduce(
    (sum, path) => sum + path.objectives_total,
    0,
  );
  const weakest = paths.flatMap((path) => path.weak_points)[0] ?? "";

  const bank = state?.question_bank;
  const weakCategory = bank?.weak_categories?.[0];

  const workspaces = state?.reading.workspaces ?? [];
  const materials = workspaces.reduce(
    (sum, workspace) => sum + workspace.materials,
    0,
  );

  const notebooks = (state?.resources ?? []).filter(
    (resource) => resource.kind === "notebook",
  );

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Tile
        // The index carries the course so it opens as this course's shelf: what
        // gets built there attaches back here instead of stranding the learner
        // one manual step away from the container they started in.
        href={
          paths.length === 1
            ? `/mastery/${encodeURIComponent(paths[0].path_id)}`
            : `/mastery?course=${course}`
        }
        icon={GraduationCap}
        label={t("Mastery Path")}
        value={
          objectivesTotal > 0 ? `${objectivesMastered}/${objectivesTotal}` : "—"
        }
        detail={
          objectivesTotal > 0
            ? weakest
              ? t("{{count}} objectives · weakest {{name}}", {
                  count: objectivesTotal,
                  name: weakest,
                })
              : t("{{count}} objectives across {{paths}} paths", {
                  count: objectivesTotal,
                  paths: paths.length,
                })
            : t("Attach or build a path to track mastery")
        }
      />
      <Tile
        href={`/space/questions?course=${course}`}
        icon={ClipboardList}
        label={t("Question Bank")}
        value={bank && bank.total > 0 ? String(bank.wrong) : "—"}
        detail={
          bank && bank.total > 0
            ? weakCategory
              ? t("wrong of {{total}} · weakest {{name}}", {
                  total: bank.total,
                  name: weakCategory.name,
                })
              : t("wrong of {{total}}", { total: bank.total })
            : t("Questions you get wrong land here")
        }
      />
      <Tile
        href={
          workspaces.length === 1
            ? `/reading/${encodeURIComponent(workspaces[0].workspace_id)}`
            : `/reading?course=${course}`
        }
        icon={ScrollText}
        label={t("Immersive Reading")}
        value={materials > 0 ? String(materials) : "—"}
        detail={
          materials > 0
            ? t("{{count}} materials open", { count: materials })
            : t("Attach a reading workspace to read alongside the tutor")
        }
      />
      <Tile
        href={`/notebooks?course=${course}`}
        icon={NotebookPen}
        label={t("Notebooks")}
        value={notebooks.length > 0 ? String(notebooks.length) : "—"}
        detail={
          notebooks.length > 0
            ? notebooks[0].label
            : t("Attach a notebook to keep this course's notes together")
        }
      />
    </div>
  );
}

function Tile({
  href,
  icon: Icon,
  label,
  value,
  detail,
}: {
  href: string;
  icon: typeof GraduationCap;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-[var(--border)] bg-[var(--card)] p-3.5 transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
    >
      <div className="flex items-center gap-2 text-[var(--muted-foreground)]">
        <Icon size={14} strokeWidth={1.7} />
        <span className="text-[11.5px]">{label}</span>
      </div>
      <p className="mt-2 font-serif text-[20px] font-semibold leading-none text-[var(--foreground)]">
        {value}
      </p>
      <p className="mt-1.5 line-clamp-2 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
        {detail}
      </p>
    </Link>
  );
}

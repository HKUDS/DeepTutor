"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Signpost } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CourseState } from "@/lib/courses-api";
import { setPendingPrompt } from "@/lib/pending-prompt";

/**
 * What this course is waiting for, decided from its own numbers.
 *
 * The course page should answer "what now?" before the learner has to ask, and
 * without spending a model round to find out: the state aggregate already knows
 * where the errors cluster, which module stalled, and what is half-read. So the
 * suggestion here is deterministic — the same evidence Course Study reads,
 * turned into one concrete move.
 *
 * Course Study remains the place for judgement (it can weigh the syllabus, ask
 * why the learner is stuck, and change its mind). This panel is the floor: even
 * with the tutor closed, opening a course tells you where you stand.
 *
 * Each action carries its opening line through `setPendingPrompt`, so taking it
 * lands in the destination already asking the right question — the same
 * hand-off contract the tutor's cards use.
 */

interface NextStep {
  /** What the learner is being told, in one line. */
  headline: string;
  /** The evidence behind it. */
  detail: string;
  action: { label: string; href: string; scope: string; prompt: string } | null;
}

function decide(
  state: CourseState | null,
  t: (key: string, options?: Record<string, unknown>) => string,
  courseId: string,
): NextStep {
  if (!state || state.resources.length === 0) {
    return {
      headline: t("This course has nothing to work with yet"),
      detail: t(
        "Attach its textbook or knowledge base and DeepTutor can start planning from the material itself.",
      ),
      action: null,
    };
  }

  // Errors first: a wrong answer is the sharpest evidence of a gap, and the
  // question bank already groups them by topic.
  const weakest = state.question_bank.weak_categories[0];
  if (weakest && weakest.wrong > 0) {
    return {
      headline: t("{{name}} is where you are losing marks", {
        name: weakest.name,
      }),
      detail: t("{{count}} questions wrong in this area", {
        count: weakest.wrong,
      }),
      action: {
        // Chat, not the question-bank list: this is a request to be taught, and
        // the list has no composer to receive it.
        label: t("Work through them"),
        href: `/chat?course=${encodeURIComponent(courseId)}&capability=course_study`,
        scope: "chat",
        prompt: t("Take me through my {{name}} mistakes one at a time.", {
          name: weakest.name,
        }),
      },
    };
  }

  // Then an unfinished path: a stalled module is a commitment already made.
  const stalled = state.mastery.paths.find(
    (path) =>
      path.objectives_total > 0 &&
      path.objectives_mastered < path.objectives_total,
  );
  if (stalled) {
    return {
      headline: t("{{name}}: {{done}} of {{total}} objectives cleared", {
        name: stalled.name,
        done: stalled.objectives_mastered,
        total: stalled.objectives_total,
      }),
      detail: stalled.weak_points[0] ?? t("Pick up where the path left off"),
      action: {
        label: t("Keep going"),
        href: `/mastery/${encodeURIComponent(stalled.path_id)}/sessions`,
        scope: "mastery_path",
        prompt: t("Continue this path from where I stopped."),
      },
    };
  }

  // Then reading that was opened but not finished.
  const workspace = state.reading.workspaces.find((item) => item.materials > 0);
  if (workspace) {
    return {
      headline: t("{{title}} is open and waiting", {
        title: workspace.title,
      }),
      detail: t("{{count}} materials in this reading workspace", {
        count: workspace.materials,
      }),
      action: {
        label: t("Read on"),
        href: `/reading/${encodeURIComponent(workspace.workspace_id)}`,
        scope: "immersive_reading",
        prompt: t("Summarise where I left off, then continue from there."),
      },
    };
  }

  // Material attached but nothing built on it yet — the useful move is to turn
  // it into something practisable.
  return {
    headline: t("The material is in place"),
    detail: t(
      "Nothing has been built from it yet — a mastery path turns it into something you can practise.",
    ),
    action: {
      label: t("Plan this course"),
      href: `/chat?course=${encodeURIComponent(courseId)}&capability=course_study`,
      scope: "chat",
      prompt: t(
        "Look at what this course has and plan what I should do first.",
      ),
    },
  };
}

export default function CourseNextStep({
  state,
  courseId,
}: {
  state: CourseState | null;
  courseId: string;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const step = decide(state, t, courseId);
  // Client navigation to these surfaces loads their chunk first, which is
  // slow enough to feel like a dead click without this.
  const [going, setGoing] = useState(false);

  const take = () => {
    if (!step.action || going) return;
    setGoing(true);
    setPendingPrompt(step.action.prompt, step.action.scope);
    router.push(step.action.href);
  };

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--secondary)]/40 p-4">
      <div className="flex items-start gap-3">
        <Signpost
          size={15}
          strokeWidth={1.8}
          className="mt-0.5 shrink-0 text-[var(--muted-foreground)]"
        />
        <div className="min-w-0 flex-1">
          <p className="font-serif text-[15px] font-semibold leading-snug text-[var(--foreground)]">
            {step.headline}
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {step.detail}
          </p>
        </div>
        {step.action ? (
          <button
            type="button"
            onClick={take}
            disabled={going}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50 disabled:opacity-60"
          >
            {going ? t("Opening") : step.action.label}
            <ArrowRight size={13} />
          </button>
        ) : null}
      </div>
    </section>
  );
}

"use client";

import { memo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BookOpen,
  ClipboardList,
  GraduationCap,
  MessageSquare,
  NotebookPen,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  courseHandoffHref,
  targetAcceptsPrompt,
  type CourseHandoffPayload,
  type CourseHandoffTarget,
} from "@/lib/course-handoff";
import { setPendingPrompt } from "@/lib/pending-prompt";

/**
 * The card Course Study uses to hand the learner to the surface that teaches.
 *
 * Course Study reads the course's state and decides what is worth doing next;
 * it does not teach. This is where that decision becomes an action the learner
 * takes — the destination, the reason, and the opening message all visible
 * before anything happens.
 *
 * The prompt is editable on purpose. It is the assistant's proposal for how to
 * start, not an instruction: a learner who wants to arrive asking something
 * slightly different should not have to first arrive, then clear the box, then
 * retype. Taking the card is also the only thing that navigates — nothing here
 * moves the page on its own.
 *
 * Mirrors `deeptutor.capabilities.course_study.tools`; the payload is read by
 * `extractCourseHandoffs` in `lib/course-handoff.ts`.
 */

const TARGET_ICONS: Record<CourseHandoffTarget, typeof BookOpen> = {
  immersive_reading: BookOpen,
  mastery_path: GraduationCap,
  question_bank: ClipboardList,
  notebook: NotebookPen,
  chat: MessageSquare,
};

const CourseHandoff = memo(function CourseHandoff({
  data,
}: {
  data: CourseHandoffPayload;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const [draft, setDraft] = useState(data.prompt);
  const Icon = TARGET_ICONS[data.target];
  const acceptsPrompt = targetAcceptsPrompt(data.target, data.ref_id);
  const needsSetup =
    !data.ref_id.trim() &&
    (data.target === "mastery_path" || data.target === "immersive_reading");
  const place: string = {
    immersive_reading: t("Immersive Reading"),
    mastery_path: t("Mastery Path"),
    question_bank: t("Question Bank"),
    notebook: t("Notebooks"),
    chat: t("Chat"),
  }[data.target];

  const go = () => {
    const opening = draft.trim();
    if (opening && acceptsPrompt) setPendingPrompt(opening, data.target);
    router.push(courseHandoffHref(data));
  };

  return (
    <div className="mt-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_4px_14px_rgba(0,0,0,0.04)]">
      <div className="flex items-start gap-3">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--foreground)_8%,transparent)] text-[var(--foreground)]/70">
          <Icon size={13} strokeWidth={1.8} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium leading-snug text-[var(--foreground)]">
            {data.reason || t("Worth doing next")}
          </div>
          <div className="mt-0.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {data.label ? `${place} · ${data.label}` : place}
            {/* No resource named means this course has none of that kind yet.
                Saying so beats letting the learner click through expecting the
                tutor's opening line and finding an empty index instead. */}
            {!data.label && needsSetup ? (
              <span className="text-[var(--muted-foreground)]/75">
                {" · "}
                {t("nothing here yet — you'll set one up")}
              </span>
            ) : null}
          </div>

          {data.prompt && acceptsPrompt ? (
            <label className="mt-3 block">
              <span className="text-[10.5px] text-[var(--muted-foreground)]/80">
                {t("Opens with")}
              </span>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={2}
                className="mt-1 w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-[12px] leading-relaxed text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]"
              />
            </label>
          ) : null}

          <button
            type="button"
            onClick={go}
            className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[11.5px] font-medium text-[var(--foreground)] transition hover:bg-[color-mix(in_srgb,var(--foreground)_5%,transparent)]"
          >
            {place}
            <span aria-hidden>→</span>
          </button>
        </div>
      </div>
    </div>
  );
});
CourseHandoff.displayName = "CourseHandoff";

export const CourseHandoffCards = memo(function CourseHandoffCards({
  handoffs,
}: {
  handoffs: CourseHandoffPayload[];
}) {
  if (handoffs.length === 0) return null;
  return (
    <>
      {handoffs.map((handoff) => (
        <CourseHandoff
          key={`${handoff.target}:${handoff.ref_id}`}
          data={handoff}
        />
      ))}
    </>
  );
});
CourseHandoffCards.displayName = "CourseHandoffCards";

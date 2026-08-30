"use client";

import { useEffect, useState } from "react";
import { Check, ListTree, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CourseState, SyllabusUnit } from "@/lib/courses-api";

/**
 * What this course is supposed to cover, and how much of it is done.
 *
 * This is the denominator. Everything else on the page counts things the
 * learner has produced — questions answered, modules passed, pages read — and
 * none of it answers "out of how much?". A syllabus is the only place that can.
 *
 * `covered` is a checkbox, never a computation. Matching a unit's topics
 * against mastered knowledge points would be a guess presented as a progress
 * bar, and a progress bar that guesses is worse than none. What the page does
 * instead is put the evidence next to the box — how many wrong questions still
 * sit under this unit's topics — and let the learner decide.
 *
 * Editing is one textarea, one unit per line, because that is how a syllabus
 * actually arrives: pasted out of a course page or a PDF, not typed into a
 * dozen little form rows.
 */

const TOPIC_SEPARATOR = "|";

function unitsToText(units: SyllabusUnit[]): string {
  return units
    .map((unit) =>
      unit.topics.length > 0
        ? `${unit.title} ${TOPIC_SEPARATOR} ${unit.topics.join(", ")}`
        : unit.title,
    )
    .join("\n");
}

/** Parse the editor back into units, keeping ids so `covered` survives a rewrite. */
function textToUnits(
  text: string,
  existing: SyllabusUnit[],
): { id?: string; title: string; topics: string[] }[] {
  const byTitle = new Map(
    existing.map((unit) => [unit.title.trim().toLowerCase(), unit]),
  );
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [rawTitle, rawTopics = ""] = line.split(TOPIC_SEPARATOR);
      const title = rawTitle.trim();
      const previous = byTitle.get(title.toLowerCase());
      return {
        ...(previous ? { id: previous.id } : {}),
        title,
        topics: rawTopics
          .split(",")
          .map((topic) => topic.trim())
          .filter(Boolean),
      };
    });
}

export default function CourseSyllabus({
  state,
  onSave,
  onToggle,
}: {
  state: CourseState | null;
  onSave: (
    units: { id?: string; title: string; topics: string[] }[],
  ) => Promise<void>;
  onToggle: (unitId: string, covered: boolean) => Promise<void>;
}) {
  const { t } = useTranslation();
  // The aggregate may predate this section on an older backend; an absent
  // syllabus reads the same as an empty one.
  const syllabus = state?.syllabus ?? {
    total: 0,
    covered: 0,
    next: null,
    units: [],
  };
  const units = syllabus.units ?? [];

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(unitsToText(units as SyllabusUnit[]));
    // Re-seeding while the editor is open would discard what is being typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, syllabus.total, syllabus.covered]);

  const save = async () => {
    setSaving(true);
    try {
      await onSave(textToUnits(draft, units as SyllabusUnit[]));
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const percent =
    syllabus.total > 0
      ? Math.round((syllabus.covered / syllabus.total) * 100)
      : 0;

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-serif text-[16px] font-semibold text-[var(--foreground)]">
            <ListTree size={15} strokeWidth={1.7} />
            {t("Syllabus")}
          </h2>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {syllabus.total > 0
              ? t("{{covered}} of {{total}} units covered", {
                  covered: syllabus.covered,
                  total: syllabus.total,
                })
              : t(
                  "What this course should cover. Without it, progress has no denominator.",
                )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditing((open) => !open)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50"
        >
          <Pencil size={12} />
          {editing ? t("Cancel") : syllabus.total > 0 ? t("Edit") : t("Add")}
        </button>
      </div>

      {syllabus.total > 0 && !editing ? (
        <div
          className="mt-3 h-1 overflow-hidden rounded-full bg-[var(--muted)]"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-[var(--foreground)]/45 transition-[width] duration-300"
            style={{ width: `${percent}%` }}
          />
        </div>
      ) : null}

      {editing ? (
        <div className="mt-3">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={8}
            placeholder={t(
              "One unit per line. Add keywords after a | so DeepTutor can tell which questions belong to it:\n\nProcesses and threads | context switch, scheduling\nVirtual memory | address translation, page replacement",
            )}
            className="w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 font-mono text-[12px] leading-relaxed text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]"
          />
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[11.5px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? t("Saving") : t("Save")}
            </button>
          </div>
        </div>
      ) : units.length === 0 ? (
        <p className="mt-3 rounded-xl border border-dashed border-[var(--border)] px-3 py-4 text-center text-[11.5px] text-[var(--muted-foreground)]">
          {t(
            "Paste the course outline and every number on this page gains a denominator.",
          )}
        </p>
      ) : (
        <ul className="mt-3 space-y-0.5">
          {units.map((unit) => {
            const isNext = syllabus.next?.id === unit.id;
            return (
              <li key={unit.id}>
                <label
                  className={`flex cursor-pointer items-start gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-[var(--muted)]/40 ${
                    isNext ? "bg-[var(--muted)]/30" : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={unit.covered}
                    onChange={(event) =>
                      void onToggle(unit.id, event.target.checked)
                    }
                    className="sr-only"
                  />
                  <span
                    aria-hidden
                    className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                      unit.covered
                        ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
                        : "border-[var(--border)]"
                    }`}
                  >
                    {unit.covered ? <Check size={11} strokeWidth={3} /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className={`block text-[12.5px] ${
                        unit.covered
                          ? "text-[var(--muted-foreground)] line-through"
                          : "text-[var(--foreground)]"
                      }`}
                    >
                      {unit.position + 1}. {unit.title}
                    </span>
                    {unit.topics.length > 0 ? (
                      <span className="mt-0.5 block truncate text-[10.5px] text-[var(--muted-foreground)]/80">
                        {unit.topics.join(" · ")}
                      </span>
                    ) : null}
                  </span>
                  {unit.wrong_questions > 0 ? (
                    <span
                      title={t(
                        "Evidence, not a verdict — you decide whether this unit is done.",
                      )}
                      className="mt-0.5 shrink-0 text-[10.5px] text-[var(--muted-foreground)]"
                    >
                      {t("{{count}} wrong", { count: unit.wrong_questions })}
                    </span>
                  ) : null}
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

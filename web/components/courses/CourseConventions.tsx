"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * The two texts that shape every conversation in a course.
 *
 * `instructions` is the learner's own: the conventions of this subject — the
 * notation it uses, how the teacher frames things, how they want to be taught.
 * It is the course's equivalent of a project's standing instructions, and the
 * reason a course is more than a folder.
 *
 * `agentNotes` is the assistant's accumulating read on the learner here, written
 * through `course_edit`. Shown read-only and collapsed: it is evidence of being
 * paid attention to, not another box to maintain. Keeping the two apart in the
 * UI mirrors keeping them apart in storage — the assistant can never quietly
 * rewrite what the learner declared.
 */
export default function CourseConventions({
  instructions,
  agentNotes,
  onSave,
}: {
  instructions: string;
  agentNotes: string;
  onSave: (instructions: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(instructions);
  const [saving, setSaving] = useState(false);
  // Shown briefly after a save so the learner knows it landed. Without it a
  // blur-save is completely silent — indistinguishable from a lost edit.
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    setDraft(instructions);
  }, [instructions]);

  const dirty = draft.trim() !== instructions.trim();

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      await onSave(draft.trim());
      setJustSaved(true);
      window.setTimeout(() => setJustSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-serif text-[16px] font-semibold text-[var(--foreground)]">
            {t("Course conventions")}
          </h2>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Notation, the teacher's angle, how you want to be taught. Every conversation in this course starts knowing this.",
            )}
          </p>
        </div>
        {!dirty && justSaved ? (
          <span className="shrink-0 text-[11.5px] text-[var(--muted-foreground)]">
            {t("Saved")}
          </span>
        ) : null}
        {dirty ? (
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="shrink-0 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[11.5px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {saving ? t("Saving") : t("Save")}
          </button>
        ) : null}
      </div>

      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={save}
        rows={3}
        maxLength={4000}
        placeholder={t(
          "e.g. Use C for examples. Focus on POSIX. Exams are proof-based.",
        )}
        className="mt-3 w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-[12.5px] leading-relaxed text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]"
      />

      {agentNotes ? (
        <details className="group mt-3">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]">
            <Sparkles size={12} strokeWidth={1.8} />
            {t("What DeepTutor has noticed")}
          </summary>
          <div className="mt-2 whitespace-pre-line rounded-xl border border-dashed border-[var(--border)] px-3 py-2.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {agentNotes}
          </div>
        </details>
      ) : null}
    </section>
  );
}

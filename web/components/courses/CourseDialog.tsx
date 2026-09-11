"use client";

import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import Modal from "@/components/common/Modal";
import { DEFAULT_COURSE_COLORS, type StudyCourse } from "@/lib/courses-api";

interface CourseDialogProps {
  open: boolean;
  course?: StudyCourse | null;
  onClose: () => void;
  onSave: (input: {
    name: string;
    description: string;
    color: string;
    default_capability: string;
    default_persona: string;
  }) => Promise<void>;
}

/**
 * Modes a course may open its conversations in.
 *
 * Not every capability: a course sets the *starting posture* for studying this
 * subject, and "start every conversation in Visualize" is not a posture anyone
 * holds. The learner can still switch to anything once inside.
 */
const DEFAULT_CAPABILITIES: { value: string; label: string }[] = [
  { value: "", label: "Chat" },
  { value: "course_study", label: "Course Study" },
  { value: "deep_solve", label: "Guided Solving" },
  { value: "deep_question", label: "Quiz" },
];

export default function CourseDialog({
  open,
  course,
  onClose,
  onSave,
}: CourseDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState(DEFAULT_COURSE_COLORS[0]);
  const [defaultCapability, setDefaultCapability] = useState("");
  const [defaultPersona, setDefaultPersona] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setName(course?.name ?? "");
    setDescription(course?.description ?? "");
    setColor(course?.color ?? DEFAULT_COURSE_COLORS[0]);
    setDefaultCapability(course?.default_capability ?? "");
    setDefaultPersona(course?.default_persona ?? "");
    setError("");
  }, [course, open]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const cleanName = name.trim();
    if (!cleanName || busy) return;
    setBusy(true);
    setError("");
    try {
      await onSave({
        name: cleanName,
        description: description.trim(),
        color,
        default_capability: defaultCapability,
        default_persona: defaultPersona.trim(),
      });
      onClose();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("Couldn't save this course."),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={course ? t("Edit course") : t("Create a course")}
      titleIcon={<BookOpen size={18} strokeWidth={1.7} />}
      width="sm"
      closeOnBackdrop={!busy}
      closeOnEscape={!busy}
    >
      <form onSubmit={submit} className="space-y-5 p-5">
        <label className="block">
          <span className="mb-1.5 block text-[12px] font-medium text-[var(--foreground)]">
            {t("Course name")}
          </span>
          <input
            data-autofocus
            value={name}
            maxLength={60}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("e.g. Operating Systems")}
            className="w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-[13px] outline-none transition-colors focus:border-[var(--ring)]"
          />
        </label>

        <label className="block">
          <span className="mb-1.5 block text-[12px] font-medium text-[var(--foreground)]">
            {t("Description")}
          </span>
          <textarea
            value={description}
            maxLength={300}
            rows={3}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("What are you learning in this course?")}
            className="w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-[13px] leading-relaxed outline-none transition-colors focus:border-[var(--ring)]"
          />
        </label>

        <fieldset>
          <legend className="mb-2 text-[12px] font-medium text-[var(--foreground)]">
            {t("Book-spine color")}
          </legend>
          <div className="flex flex-wrap gap-2">
            {DEFAULT_COURSE_COLORS.map((candidate) => (
              <button
                key={candidate}
                type="button"
                onClick={() => setColor(candidate)}
                aria-label={`${t("Choose color")} ${candidate}`}
                aria-pressed={color === candidate}
                className="h-8 w-8 rounded-full border-2 transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
                style={{
                  backgroundColor: candidate,
                  borderColor:
                    color === candidate ? "var(--foreground)" : "transparent",
                }}
              />
            ))}
          </div>
        </fieldset>

        {/* What a new conversation in this course inherits. Stored on the
            course and applied by the composer when one opens here, so a subject
            that is always studied one way does not have to be set up by hand
            every time. */}
        <fieldset className="border-t border-[var(--border)]/70 pt-4">
          <legend className="pr-2 text-[12px] font-medium text-[var(--foreground)]">
            {t("How conversations here start")}
          </legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-[11.5px] text-[var(--muted-foreground)]">
                {t("Mode")}
              </span>
              <select
                value={defaultCapability}
                onChange={(event) => setDefaultCapability(event.target.value)}
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] outline-none transition-colors focus:border-[var(--ring)]"
              >
                {DEFAULT_CAPABILITIES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.label)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-[11.5px] text-[var(--muted-foreground)]">
                {t("Persona")}
              </span>
              <input
                value={defaultPersona}
                maxLength={80}
                onChange={(event) => setDefaultPersona(event.target.value)}
                placeholder={t("Default")}
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] outline-none transition-colors focus:border-[var(--ring)]"
              />
            </label>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Applied when a conversation opens from this course, along with its knowledge bases. You can change any of it once inside.",
            )}
          </p>
        </fieldset>

        {error ? (
          <p role="alert" className="text-[12px] text-[var(--destructive)]">
            {error}
          </p>
        ) : null}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg px-3 py-2 text-[13px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
          >
            {t("Cancel")}
          </button>
          <button
            type="submit"
            disabled={!name.trim() || busy}
            className="rounded-lg bg-[var(--foreground)] px-4 py-2 text-[13px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {busy
              ? t("Saving...")
              : course
                ? t("Save changes")
                : t("Create course")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

"use client";

import { Check, Loader2, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  confirmPointLecture,
  discardPointLectureDraft,
  type LectureChange,
} from "@/lib/learning-api";
import type { LectureRevisionPreview } from "@/lib/lecture-preview";

const OP_LABEL: Record<string, string> = {
  added: "Added section",
  removed: "Removed section",
  replaced: "Rewritten section",
};

/**
 * The lecture change a reply proposed, with the two buttons that make it real.
 *
 * Shown instead of applying automatically. A lecture is a long document the
 * learner may have written parts of themselves; a model that rewrites it in
 * place is not a convenience, it is a silent edit to their notes. The diff is
 * section-level so what they are agreeing to is legible at a glance.
 */
export function LectureRevisionCard({
  preview,
  pathId,
  knowledgePointId,
  onApplied,
}: {
  preview: LectureRevisionPreview;
  pathId: string;
  knowledgePointId: string;
  onApplied: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<"apply" | "discard" | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const apply = async () => {
    setBusy("apply");
    setError("");
    try {
      await confirmPointLecture(pathId, knowledgePointId, {
        session_id: preview.sessionId,
        ...(preview.baseRevision ? { expected_revision: preview.baseRevision } : {}),
      });
      setDone(true);
      onApplied();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t("That did not work"));
    } finally {
      setBusy(null);
    }
  };

  const discard = async () => {
    setBusy("discard");
    setError("");
    try {
      await discardPointLectureDraft(pathId, knowledgePointId, preview.sessionId);
      setDone(true);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t("That did not work"));
    } finally {
      setBusy(null);
    }
  };

  if (done) {
    return (
      <p className="mt-3 text-[12px] text-[var(--muted-foreground)]">
        {t("Lecture updated")}
      </p>
    );
  }

  return (
    <section className="mt-3 overflow-hidden rounded-xl border border-[var(--primary)]/30 bg-[var(--card)]">
      <header className="flex items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--primary)]/[0.05] px-3.5 py-2">
        <h3 className="text-[12.5px] font-semibold text-[var(--foreground)]">
          {t("Proposed lecture change")}
        </h3>
        <span className="text-[11px] text-[var(--muted-foreground)]">
          {t("Not applied yet")}
        </span>
      </header>
      <div className="max-h-[280px] space-y-2 overflow-y-auto px-3.5 py-2.5">
        {preview.changes.length === 0 ? (
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {t("The revision changed nothing the reader can see.")}
          </p>
        ) : null}
        {preview.changes.map((change, index) => (
          <LectureChangeRow key={`${change.heading}-${index}`} change={change} />
        ))}
      </div>
      {error ? (
        <p className="px-3.5 pb-2 text-[11.5px] text-[var(--destructive)]">{error}</p>
      ) : null}
      <footer className="flex items-center gap-1.5 border-t border-[var(--border)] px-3.5 py-2">
        <button
          type="button"
          onClick={() => void apply()}
          disabled={busy !== null}
          className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
        >
          {busy === "apply" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Check className="h-3 w-3" />
          )}
          {t("Apply to lecture")}
        </button>
        <button
          type="button"
          onClick={() => void discard()}
          disabled={busy !== null}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1 text-[11.5px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
        >
          <X className="h-3 w-3" />
          {t("Discard")}
        </button>
      </footer>
    </section>
  );
}

function LectureChangeRow({ change }: { change: LectureChange }) {
  const { t } = useTranslation();
  const label = t(OP_LABEL[change.op ?? ""] ?? "Section changed");
  return (
    <details className="rounded-lg border border-[var(--border)] bg-[var(--background)]/60" open>
      <summary className="cursor-pointer select-none px-2.5 py-1.5 text-[12px]">
        <span className="font-medium text-[var(--foreground)]">
          {change.heading || t("(intro)")}
        </span>
        <span className="ml-1.5 text-[11px] text-[var(--muted-foreground)]">{label}</span>
      </summary>
      <div className="space-y-1 px-2.5 pb-2">
        {change.before ? (
          <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-red-500/[0.07] px-2 py-1.5 font-sans text-[11.5px] leading-5 text-[var(--foreground)] line-through decoration-red-500/40">
            {change.before}
          </pre>
        ) : null}
        {change.after ? (
          <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-emerald-500/[0.08] px-2 py-1.5 font-sans text-[11.5px] leading-5 text-[var(--foreground)]">
            {change.after}
          </pre>
        ) : null}
      </div>
    </details>
  );
}

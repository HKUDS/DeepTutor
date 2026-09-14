"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ArrowRight, BookOpen, CircleCheck, Flag, Trash2 } from "lucide-react";

import type { MasteryTopic } from "@/lib/learning-api";
import { deleteProgress } from "@/lib/learning-api";

import { ConfirmDialog } from "./ConfirmDialog";
import { topicDisplayName, type Translate } from "./format";
import { ImportModulesFromBookDialog } from "./ImportModulesFromBookDialog";
import { ProgressRing } from "./ProgressRing";

export function TopicMapCard({
  topic,
  stage,
  onDeleted,
  onImported,
}: {
  topic: MasteryTopic;
  /** progress summaries' current_stage for this path ("" when unknown). */
  stage?: string;
  onDeleted: (pathId: string) => void;
  onImported: (pathId: string, moduleCount: number) => void;
}) {
  const { t } = useTranslation();
  const { map, metadata } = topic;
  const total = map.counts.total;
  const mastered = map.counts.mastered;
  const progress = total ? mastered / total : 0;
  const due = topic.reviews.filter((review) => review.due).length;
  const displayName = topicDisplayName(topic, t);

  const isEmpty = map.modules.length === 0;
  // A path sits in the diagnostic stage until its first diagnostic exercise is
  // finished; with no modules there is nothing to diagnose, so the empty-topic
  // guidance below takes over instead.
  const awaitingDiagnostic = stage === "diagnostic" && !isEmpty;

  const [importOpen, setImportOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteTriggerRef = useRef<HTMLButtonElement | null>(null);

  // No backend archive endpoint exists for topics (only
  // DELETE /api/mastery-paths/progress/{book_id}), so the empty-topic exit is
  // a confirmed delete rather than a collapsible archive.
  const removeTopic = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteProgress(topic.path_id);
      setDeleteOpen(false);
      onDeleted(topic.path_id);
    } catch (reason) {
      setDeleteError(
        reason instanceof Error ? reason.message : t("Delete failed."),
      );
      setDeleteOpen(false);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="mastery-map-card group overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
      <Link
        href={`/mastery/${encodeURIComponent(topic.path_id)}`}
        aria-label={t(
          "Open {{name}}, {{mastered}} of {{total}} knowledge points complete",
          {
            name: displayName,
            mastered,
            total,
          },
        )}
        className="block focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-inset"
      >
        <div className="flex items-start gap-3.5 p-4">
          <ProgressRing value={total ? mastered / total : 0} />
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3">
              <h2 className="min-w-0 flex-1 truncate font-serif text-[15px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
                {displayName}
              </h2>
              {map.complete && (
                <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-[var(--primary)]" />
              )}
            </div>
            <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-[var(--muted-foreground)]">
              {metadata.description || metadata.goal}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] tabular-nums text-[var(--muted-foreground)]">
              <span className="whitespace-nowrap">
                {t("{{count}} modules", { count: map.modules.length })}
              </span>
              <span className="whitespace-nowrap">
                {mastered}/{total} {t("knowledge points")}
              </span>
              <span className="whitespace-nowrap">
                {t("{{count}} sessions", { count: topic.session_count })}
              </span>
            </div>
          </div>
        </div>
        {awaitingDiagnostic && (
          <div className="flex items-center gap-2 border-t border-[var(--border)] bg-[var(--primary)]/[0.05] px-4 py-2.5 text-[11px] font-medium text-[var(--primary)]">
            <Flag className="h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 flex-1">
              {t(
                "Finish the first diagnostic exercise to enter the learning stage",
              )}
            </span>
            <ArrowRight className="h-3.5 w-3.5 shrink-0" />
          </div>
        )}
      </Link>

      {isEmpty && (
        <div className="border-t border-[var(--border)] bg-[var(--muted-foreground)]/[0.05] px-4 py-3.5">
          <p className="text-[12px] leading-5 text-[var(--muted-foreground)]">
            {t("This topic has no modules yet.")}
            <br />
            {t(
              "Import a textbook to build the route, or delete this topic and start over.",
            )}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setImportOpen(true)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-xs font-medium text-[var(--primary-foreground)] transition hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
            >
              <BookOpen className="h-3.5 w-3.5" />
              {t("Generate modules from a book")}
            </button>
            <button
              type="button"
              ref={deleteTriggerRef}
              onClick={() => setDeleteOpen(true)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-xs font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
            >
              <Trash2 className="h-3.5 w-3.5" />
              {t("Delete")}
            </button>
          </div>
          {deleteError && (
            <p className="mt-2 text-[11px] text-red-600">{deleteError}</p>
          )}
        </div>
      )}

      {importOpen && (
        <ImportModulesFromBookDialog
          pathId={topic.path_id}
          onClose={() => setImportOpen(false)}
          onImported={(moduleCount) => {
            setImportOpen(false);
            onImported(topic.path_id, moduleCount);
          }}
          returnFocusRef={deleteTriggerRef}
        />
      )}
      {deleteOpen && (
        <ConfirmDialog
          title={t("Delete topic “{{name}}”?", { name: displayName })}
          description={t(
            "This permanently removes the topic, its modules, and all learning progress.",
          )}
          confirmLabel={t("Delete")}
          cancelLabel={t("Cancel")}
          destructive
          busy={deleting}
          onConfirm={() => void removeTopic()}
          onClose={() => setDeleteOpen(false)}
          returnFocusRef={deleteTriggerRef}
        />
      )}
    </div>
  );
}

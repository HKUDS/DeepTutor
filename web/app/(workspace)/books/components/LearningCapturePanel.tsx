"use client";

import { Check, ChevronDown, ListFilter, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { LearningCapture } from "@/lib/book-types";

interface LearningCapturePanelProps {
  captures: LearningCapture[];
  loading: boolean;
  onApprove: (capture: LearningCapture) => Promise<void> | void;
  onReject: (capture: LearningCapture) => Promise<void> | void;
}

const reviewableStatuses = new Set<LearningCapture["status"]>([
  "captured",
  "drafted",
  "pending_confirmation",
]);

function statusText(
  status: LearningCapture["status"],
  t: (key: string, values?: any) => string,
) {
  const map: Record<string, string> = {
    captured: t("Captured"),
    drafted: t("Drafted"),
    pending_confirmation: t("Pending confirmation"),
    approved: t("Approved"),
    delivered: t("Delivered"),
    imported: t("Imported"),
    rejected: t("Rejected"),
  };
  return map[status] || status;
}

/**
 * Highlights the reader saved, waiting to be confirmed.
 *
 * Two changes from the version that sat permanently under every chapter of
 * every book:
 *
 * - **It is absent when it is empty.** A panel whose whole content was
 *   "No captures awaiting review." occupied a strip of the reader in every
 *   book, for every reader, most of whom have never saved a highlight. There
 *   is nothing to report until there is something to report.
 * - **It says what it is for.** "Learning capture inbox" named an internal
 *   pipeline; nothing on screen connected it to selecting text in a chapter,
 *   or said where a confirmed highlight goes.
 */
export default function LearningCapturePanel({
  captures,
  loading,
  onApprove,
  onReject,
}: LearningCapturePanelProps) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState(true);

  const reviewable = useMemo(
    () => captures.filter((capture) => reviewableStatuses.has(capture.status)),
    [captures],
  );
  const filteredCaptures = showAll ? captures : reviewable;

  // Nothing saved and nothing loading: no panel at all.
  if (!captures.length) return null;

  return (
    <section className="mx-auto w-full max-w-[78ch] space-y-2">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          className="group/inbox inline-flex min-w-0 items-center gap-2 text-left text-[13px] font-semibold text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          <ChevronDown
            className={`h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)] opacity-50 transition-transform ${
              open ? "" : "-rotate-90"
            }`}
          />
          {t("Saved highlights")}
          <span className="font-normal text-[var(--muted-foreground)] opacity-60">
            {reviewable.length
              ? t("{{count}} awaiting confirmation", {
                  count: reviewable.length,
                })
              : t("{{count}} saved", { count: captures.length })}
          </span>
        </button>
        {open && (
          <button
            type="button"
            onClick={() => setShowAll((current) => !current)}
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            title={
              showAll
                ? t("Show only reviewable captures")
                : t("Show all captures")
            }
          >
            <ListFilter className="h-3.5 w-3.5" />
            {showAll ? t("Review") : t("All")}
          </button>
        )}
      </div>

      {!open ? null : loading && filteredCaptures.length === 0 ? (
        <div className="text-xs text-[var(--muted-foreground)]">
          {t("Loading captures…")}
        </div>
      ) : filteredCaptures.length === 0 ? (
        <div className="text-xs text-[var(--muted-foreground)]">
          {t("Nothing left to confirm — switch to All to see saved highlights.")}
        </div>
      ) : (
        <div className="max-h-52 space-y-2 overflow-y-auto pr-1">
          {filteredCaptures.map((capture) => {
            const canReview = reviewableStatuses.has(capture.status);
            return (
              <article
                key={capture.id}
                className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-2"
              >
                <div className="mb-1 flex items-start justify-between gap-2 text-[11px]">
                  <span className="rounded-md bg-[var(--muted)] px-2 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                    {statusText(capture.status, t)}
                  </span>
                  <span className="text-[10px] text-[var(--muted-foreground)]">
                    {capture.chapter_title || t("Unknown chapter")}
                  </span>
                </div>
                <p className="whitespace-pre-wrap text-sm text-[var(--foreground)]">
                  {capture.source_text}
                </p>
                {capture.user_note ? (
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                    {t("Note")}: {capture.user_note}
                  </p>
                ) : null}
                <div className="mt-2 flex items-center gap-2">
                  {canReview && (
                    <>
                      <button
                        type="button"
                        onClick={() => void onApprove(capture)}
                        className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2 py-1 text-[11px] font-medium text-[var(--primary-foreground)] hover:opacity-90"
                      >
                        <Check className="h-3.5 w-3.5" />
                        {t("Approve")}
                      </button>
                      <button
                        type="button"
                        onClick={() => void onReject(capture)}
                        className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
                      >
                        <X className="h-3.5 w-3.5" />
                        {t("Reject")}
                      </button>
                    </>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {open && reviewable.length > 0 && (
        <p className="text-[11px] leading-snug text-[var(--muted-foreground)] opacity-70">
          {t(
            "Text you select in a chapter is saved here first. Confirmed highlights are exported to MarginNote.",
          )}
        </p>
      )}
    </section>
  );
}

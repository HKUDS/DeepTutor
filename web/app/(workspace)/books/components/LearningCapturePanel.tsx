"use client";

import { Check, ListFilter, X } from "lucide-react";
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

export default function LearningCapturePanel({
  captures,
  loading,
  onApprove,
  onReject,
}: LearningCapturePanelProps) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);

  const filteredCaptures = useMemo(() => {
    if (showAll) return captures;
    return captures.filter((capture) => reviewableStatuses.has(capture.status));
  }, [captures, showAll]);

  return (
    <section className="mx-auto w-full max-w-[78ch] space-y-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Learning capture inbox")}
        </h2>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-xs text-[var(--muted-foreground)]">
            {filteredCaptures.length}
          </span>
          <button
            type="button"
            onClick={() => setShowAll((current) => !current)}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--muted-foreground)] hover:border-[var(--primary)]/40 hover:text-[var(--foreground)]"
            title={
              showAll
                ? t("Show only reviewable captures")
                : t("Show all captures")
            }
          >
            <ListFilter className="h-3.5 w-3.5" />
            {showAll ? t("Review") : t("All")}
          </button>
        </div>
      </div>

      {loading && filteredCaptures.length === 0 ? (
        <div className="text-xs text-[var(--muted-foreground)]">
          {t("Loading captures…")}
        </div>
      ) : filteredCaptures.length === 0 ? (
        <div className="text-xs text-[var(--muted-foreground)]">
          {showAll ? t("No captures yet.") : t("No captures awaiting review.")}
        </div>
      ) : (
        <div className="max-h-52 space-y-2 overflow-y-auto pr-1">
          {filteredCaptures.map((capture) => {
            const reviewable = reviewableStatuses.has(capture.status);
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
                  {reviewable && (
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
    </section>
  );
}

"use client";

import { Check, ChevronDown, ChevronUp, Loader2, Pencil } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";
import {
  confirmPointLecture,
  fetchPointLecture,
  type PointLecture,
} from "@/lib/learning-api";

/** A draft rolled after a turn lands just after the stream closes. */
const LATE_DRAFT_RETRIES = [1500, 3000, 5000];

/**
 * "Here is the lecture for this section — is it right?"
 *
 * Appears in the study conversation once the runtime has rolled a draft, and
 * stays until the learner decides. Collapsed by default because the point is
 * to offer a decision, not to dump a document over the tutoring they were
 * reading; expanded, it is the actual text they are agreeing to.
 *
 * It never disappears on its own. A learner who keeps talking keeps the same
 * card — the draft behind it rolls forward — because a second card asking
 * "which of these two lectures is yours?" has no good answer.
 */
export function LectureDraftCard({
  pathId,
  knowledgePointId,
  sessionId,
  pointName,
  refreshToken = 0,
  onConfirmed,
}: {
  pathId: string;
  knowledgePointId: string;
  sessionId: string;
  pointName: string;
  /** Changes after every finished turn, so a newly rolled draft shows up. */
  refreshToken?: number;
  onConfirmed?: () => void;
}) {
  const { t } = useTranslation();
  const [lecture, setLecture] = useState<PointLecture | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!pathId || !knowledgePointId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    const read = async () => {
      try {
        const result = await fetchPointLecture(pathId, knowledgePointId);
        if (cancelled) return;
        setLecture(result);
        // Already settled by someone else (a review tab, or leaving the
        // point): the card has nothing left to ask.
        setDone(result.status === "confirmed");
        // The backend rolls the draft just after the turn's message is
        // persisted, which can be a beat behind the stream ending. Look again
        // a few times rather than showing nothing for a draft that exists.
        if (result.status === "none" && attempt < LATE_DRAFT_RETRIES.length) {
          timer = setTimeout(() => void read(), LATE_DRAFT_RETRIES[attempt++]);
        }
      } catch {
        if (!cancelled) setLecture(null);
      }
    };
    void read();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [knowledgePointId, pathId, refreshToken]);

  if (done) return null;
  if (lecture === null) return null;
  if (lecture.status !== "draft_only") return null;

  const confirm = async () => {
    setBusy(true);
    setError("");
    try {
      await confirmPointLecture(pathId, knowledgePointId, {
        session_id: lecture?.draft?.session_id || sessionId,
        ...(lecture?.revision ? { expected_revision: lecture.revision } : {}),
      });
      setDone(true);
      onConfirmed?.();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t("That did not work"));
    } finally {
      setBusy(false);
    }
  };

  const body = lecture?.body ?? "";

  return (
    <section className="rounded-xl border border-[var(--primary)]/30 bg-[var(--primary)]/[0.04] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-[var(--foreground)]">
            {pointName
              ? t("Lecture for “{{name}}”", { name: pointName })
              : t("Lecture for this section")}
          </h2>
          <p className="mt-0.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
            {t(
              "Written from this conversation. Confirm it to make it the lecture you review from — or keep talking and it will be updated first.",
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => void confirm()}
            disabled={busy || !body}
            className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
          >
            {busy ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Check className="h-3 w-3" />
            )}
            {t("Confirm this section's lecture")}
          </button>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {open ? t("Hide") : t("Read it")}
          </button>
        </div>
      </div>
      {error ? (
        <p className="mt-2 text-[12px] text-[var(--destructive)]">{error}</p>
      ) : null}
      {open ? (
        <div className="mt-3 max-h-[50vh] overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-3">
          {body ? (
            <RichMarkdownRenderer content={body} enableMath enableCode variant="default" />
          ) : (
            <p className="text-[12px] text-[var(--muted-foreground)]">
              <Pencil className="mr-1 inline h-3 w-3" />
              {t("The lecture is still being written.")}
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}

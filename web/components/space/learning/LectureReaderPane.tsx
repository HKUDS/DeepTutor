"use client";

import { AlertCircle, CheckCircle2, Loader2, Pencil, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";
import Tooltip from "@/shared/ui/Tooltip";
import {
  confirmPointLecture,
  discardPointLectureDraft,
  fetchPointLecture,
  revertPointLecture,
  savePointLecture,
  type PointLecture,
} from "@/lib/learning-api";

/**
 * The lecture half of the review screen.
 *
 * Three states, rendered differently on purpose, because they ask the learner
 * to do different things:
 *
 * - `confirmed` — settled text. Read it; edit it by hand if you want.
 * - `draft_only` — a summary of the study conversation that *nobody
 *   confirmed*. Shown, because hiding it would leave review blank after a
 *   successful study section, but marked, because it is not settled content
 *   and the learner has to press the button.
 * - `stale_from_study` — confirmed text that study has since moved past. A
 *   chip, not a warning: their lecture is still theirs.
 */
export function LectureReaderPane({
  pathId,
  knowledgePointId,
  pointName,
  onLectureConfirmed,
}: {
  pathId: string;
  knowledgePointId: string;
  pointName: string;
  /** Lets the review chat know a draft became the real lecture. */
  onLectureConfirmed?: () => void;
}) {
  const { t } = useTranslation();
  // Keyed by point so switching points shows a loading state instead of the
  // previous point's lecture for a frame.
  const [loaded, setLoaded] = useState<{ pointId: string; lecture: PointLecture | null } | null>(
    null,
  );
  const [error, setError] = useState<{ pointId: string; message: string } | null>(null);
  const [busy, setBusy] = useState<"confirm" | "discard" | "revert" | "save" | null>(null);
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!pathId || !knowledgePointId) return;
    let cancelled = false;
    setError(null);
    setEditing(false);
    void fetchPointLecture(pathId, knowledgePointId)
      .then((result) => {
        if (!cancelled) setLoaded({ pointId: knowledgePointId, lecture: result });
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError({
            pointId: knowledgePointId,
            message: reason instanceof Error ? reason.message : t("The lecture could not be loaded"),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [knowledgePointId, pathId, t]);

  const lecture = loaded?.pointId === knowledgePointId ? loaded.lecture : null;
  const currentError = error?.pointId === knowledgePointId ? error.message : "";
  const status = lecture?.status ?? "none";

  const refresh = async () => {
    const next = await fetchPointLecture(pathId, knowledgePointId);
    setLoaded({ pointId: knowledgePointId, lecture: next });
    return next;
  };

  const run = async (kind: NonNullable<typeof busy>, work: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await work();
    } catch (reason: unknown) {
      setError({
        pointId: knowledgePointId,
        message: reason instanceof Error ? reason.message : t("That did not work"),
      });
    } finally {
      setBusy(null);
    }
  };

  const confirm = () =>
    run("confirm", async () => {
      await confirmPointLecture(pathId, knowledgePointId, {
        session_id: lecture?.draft?.session_id ?? "",
        // Only a revision of an existing lecture has a basis to conflict with.
        ...(lecture?.revision ? { expected_revision: lecture.revision } : {}),
      });
      await refresh();
      onLectureConfirmed?.();
    });

  const discard = () =>
    run("discard", async () => {
      await discardPointLectureDraft(pathId, knowledgePointId, lecture?.draft?.session_id ?? "");
      await refresh();
    });

  const revert = () =>
    run("revert", async () => {
      await revertPointLecture(pathId, knowledgePointId, lecture?.draft?.session_id ?? "");
      await refresh();
    });

  const saveEdit = () =>
    run("save", async () => {
      const text = draftText.trim();
      if (!text) return;
      await savePointLecture(pathId, knowledgePointId, {
        body: text,
        expected_revision: lecture?.revision ?? 1,
      });
      setEditing(false);
      await refresh();
    });

  const body = useMemo(() => lecture?.body ?? "", [lecture]);

  if (!knowledgePointId) return null;

  return (
    <section className="flex h-full min-h-0 flex-col border-r border-[var(--border)] bg-[var(--card)]/20">
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <h2 className="truncate text-[12.5px] font-semibold text-[var(--foreground)]">
              {pointName || t("Lecture")}
            </h2>
            {status === "draft_only" ? (
              <span className="shrink-0 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400">
                {t("Unconfirmed")}
              </span>
            ) : null}
            {lecture?.stale_from_study ? (
              <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                {t("Study moved on")}
              </span>
            ) : null}
          </div>
          <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
            {status === "confirmed"
              ? lecture?.source === "implicit"
                ? t("Saved automatically when you moved on")
                : t("Confirmed lecture")
              : status === "draft_only"
                ? t("A summary of your study conversation. Confirm it to make it final.")
                : t("No lecture yet for this knowledge point.")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {busy ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin text-[var(--muted-foreground)]" />
          ) : null}
          {status === "confirmed" && !editing ? (
            <Tooltip label={t("Edit lecture")} side="bottom">
              <button
                type="button"
                onClick={() => {
                  setDraftText(body);
                  setEditing(true);
                }}
                className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
                aria-label={t("Edit lecture")}
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </Tooltip>
          ) : null}
          {status === "confirmed" && lecture?.source === "implicit" ? (
            <Tooltip label={t("Undo automatic save")} side="bottom">
              <button
                type="button"
                onClick={() => void revert()}
                disabled={busy !== null}
                className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)] disabled:opacity-40"
                aria-label={t("Undo automatic save")}
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            </Tooltip>
          ) : null}
        </div>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {currentError ? (
          <p className="flex items-start gap-1.5 text-[12px] text-[var(--destructive)]">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {currentError}
          </p>
        ) : null}

        {!lecture && !currentError ? (
          <div className="flex h-full items-center justify-center text-[var(--muted-foreground)]">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        ) : null}

        {status === "draft_only" && !editing ? (
          <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/[0.07] px-3 py-2">
            <p className="text-[11.5px] leading-5 text-[var(--foreground)]">
              {t(
                "This is a draft from your study conversation. It has not been confirmed yet, so a later study session can still change it.",
              )}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => void confirm()}
                disabled={busy !== null}
                className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
              >
                <CheckCircle2 className="h-3 w-3" />
                {t("Confirm this lecture")}
              </button>
              <button
                type="button"
                onClick={() => void discard()}
                disabled={busy !== null}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1 text-[11.5px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
              >
                <X className="h-3 w-3" />
                {t("Discard draft")}
              </button>
            </div>
          </div>
        ) : null}

        {status === "none" && !currentError ? (
          <p className="text-[12px] leading-5 text-[var(--muted-foreground)]">
            {t(
              "This point has nothing to read yet. Study it first — the lecture is written from that conversation.",
            )}
          </p>
        ) : null}

        {editing ? (
          <div className="flex h-full min-h-0 flex-col">
            <textarea
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              aria-label={t("Edit lecture")}
              className="min-h-[240px] flex-1 resize-none rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 font-mono text-[12.5px] leading-6 text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--primary)]"
            />
            <div className="mt-2 flex shrink-0 gap-1.5">
              <button
                type="button"
                onClick={() => void saveEdit()}
                disabled={busy !== null || !draftText.trim()}
                className="rounded-md bg-[var(--primary)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
              >
                {t("Save lecture")}
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                disabled={busy !== null}
                className="rounded-md border border-[var(--border)] px-2.5 py-1 text-[11.5px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                {t("Cancel")}
              </button>
            </div>
          </div>
        ) : body ? (
          <div className="mastery-lecture-body">
            <RichMarkdownRenderer content={body} enableMath enableCode variant="default" />
          </div>
        ) : null}
      </div>
    </section>
  );
}

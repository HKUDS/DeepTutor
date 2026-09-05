"use client";

import {
  CheckCircle2,
  Loader2,
  Pause,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getFocusState,
  startFocusReading,
  stopFocusReading,
  submitFocusCheck,
  type FocusAttempt,
  type FocusState,
} from "@/lib/reading-api";
import { focusProgress } from "@/lib/reading-focus";

export function FocusReadingPanel({
  materialId,
  focus,
  onFocusChange,
  onNavigate,
  onClose,
  onError,
}: {
  materialId: string;
  focus: FocusState | null;
  onFocusChange: (focus: FocusState) => void;
  onNavigate: (locator: number) => void;
  onClose: () => void;
  onError: (message: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [summary, setSummary] = useState("");
  const [reflection, setReflection] = useState("");
  const [attempt, setAttempt] = useState<FocusAttempt | null>(null);
  const [busy, setBusy] = useState(false);
  const requestRef = useRef(0);

  useEffect(
    () => () => {
      // A response for a closed panel or another material must not replace the
      // current reader's state after workspace navigation.
      requestRef.current += 1;
    },
    [],
  );

  useEffect(() => {
    setSummary("");
    setReflection("");
    setAttempt(null);
  }, [focus?.run_id, focus?.expected_checkpoint?.checkpoint_id]);

  const run = async (action: () => Promise<FocusState>, reset = false) => {
    const request = ++requestRef.current;
    setBusy(true);
    try {
      const next = await action();
      if (request !== requestRef.current) return;
      onFocusChange(next);
      if (reset && next.expected_checkpoint)
        onNavigate(next.expected_checkpoint.start_locator);
    } catch (error) {
      if (request === requestRef.current)
        onError(
          error instanceof Error ? error.message : t("Focus Reading failed."),
        );
    } finally {
      if (request === requestRef.current) setBusy(false);
    }
  };

  const submit = async () => {
    if (!focus?.expected_checkpoint || busy) return;
    const captured = focus;
    const capturedCheckpoint = focus.expected_checkpoint;
    const request = ++requestRef.current;
    setBusy(true);
    setAttempt(null);
    try {
      const result = await submitFocusCheck(materialId, captured, {
        checkpoint_id: capturedCheckpoint.checkpoint_id,
        summary: summary.trim(),
        reflection: reflection.trim(),
        locale: i18n.resolvedLanguage ?? i18n.language,
      });
      if (request !== requestRef.current) return;
      setAttempt(result.attempt);
      onFocusChange(result.focus);
      if (result.attempt.passed) {
        setSummary("");
        setReflection("");
        if (result.focus.expected_checkpoint)
          onNavigate(result.focus.expected_checkpoint.start_locator);
      } else {
        onNavigate(capturedCheckpoint.start_locator);
      }
    } catch (error) {
      if (request !== requestRef.current) return;
      onError(
        error instanceof Error ? error.message : t("Focus-Check failed."),
      );
      // A 409 means the browser state is stale. Refetch instead of making an
      // optimistic local progression decision.
      try {
        const next = await getFocusState(materialId);
        if (request === requestRef.current) onFocusChange(next);
      } catch {
        // Keep the first, actionable error visible.
      }
    } finally {
      if (request === requestRef.current) setBusy(false);
    }
  };

  const progress = focusProgress(focus);
  const checkpoint = focus?.expected_checkpoint;
  const summaryReady = summary.trim().length >= 20;
  const reflectionReady = reflection.trim().length >= 10;

  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]">
      <section
        role="dialog"
        aria-modal="true"
        aria-label={t("Focus Reading")}
        className="flex max-h-[min(680px,92vh)] w-full max-w-[620px] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--background)] shadow-2xl"
      >
        <header className="flex items-center gap-3 border-b border-[var(--border)] px-5 py-4">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--primary)]/12 text-[var(--primary)]">
            <Sparkles size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
              {t("Focus Reading")}
            </h2>
            {focus?.active && (
              <p className="text-[11.5px] text-[var(--muted-foreground)]">
                {t("{{passed}} of {{total}} checkpoints complete", progress)}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="grid h-8 w-8 place-items-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <X size={16} />
          </button>
        </header>

        <div className="dt-reader-scroll overflow-y-auto p-5">
          {!focus?.active ? (
            <div className="space-y-4 text-center">
              <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Read one checkpoint at a time, then briefly explain what happened and what affected you.",
                )}
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void run(() => startFocusReading(materialId), true)
                }
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Sparkles size={15} />
                )}
                {t("Start Focus Reading")}
              </button>
            </div>
          ) : focus.completed ? (
            <div className="space-y-4 text-center">
              <CheckCircle2 className="mx-auto text-emerald-500" size={34} />
              <p className="font-medium text-[var(--foreground)]">
                {t("You completed every Focus-Check in this book.")}
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void run(() => startFocusReading(materialId, true), true)
                }
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-xs font-medium hover:bg-[var(--muted)] disabled:opacity-50"
              >
                <RotateCcw size={14} />
                {t("Read immersively again")}
              </button>
            </div>
          ) : checkpoint ? (
            <div className="space-y-4">
              <div className="rounded-xl border border-[var(--border)] bg-[var(--muted)]/30 p-3">
                <p className="text-[10.5px] font-semibold uppercase tracking-wide text-[var(--primary)]">
                  {t("Current checkpoint")}
                </p>
                <p className="mt-1 text-sm font-medium text-[var(--foreground)]">
                  {checkpoint.title}
                </p>
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  {t("{{start}}–{{end}} · {{characters}} characters", {
                    start: checkpoint.start_locator,
                    end: checkpoint.end_locator,
                    characters: checkpoint.char_count.toLocaleString(),
                  })}
                </p>
              </div>

              {attempt && (
                <div
                  role="status"
                  className={`rounded-xl border p-3 text-sm ${
                    attempt.passed
                      ? "border-emerald-500/30 bg-emerald-500/10"
                      : "border-amber-500/30 bg-amber-500/10"
                  }`}
                >
                  <p className="font-semibold">
                    {attempt.passed
                      ? t("Passed · {{score}}/100", { score: attempt.score })
                      : t("Not yet · {{score}}/100", { score: attempt.score })}
                  </p>
                  <p className="mt-1 leading-relaxed text-[var(--muted-foreground)]">
                    {attempt.feedback}
                  </p>
                </div>
              )}

              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-[var(--foreground)]">
                  {t("What happened or what ideas were developed?")}
                </span>
                <textarea
                  value={summary}
                  onChange={(event) => setSummary(event.target.value)}
                  rows={4}
                  maxLength={20_000}
                  className="w-full resize-y rounded-xl border border-[var(--border)] bg-transparent p-3 text-sm outline-none focus:border-[var(--primary)]"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-[var(--foreground)]">
                  {t("What affected you most, and why?")}
                </span>
                <textarea
                  value={reflection}
                  onChange={(event) => setReflection(event.target.value)}
                  rows={3}
                  maxLength={10_000}
                  className="w-full resize-y rounded-xl border border-[var(--border)] bg-transparent p-3 text-sm outline-none focus:border-[var(--primary)]"
                />
              </label>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void run(() => stopFocusReading(materialId))}
                    className="inline-flex h-9 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
                  >
                    <Pause size={13} />
                    {t("Pause")}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void run(() => startFocusReading(materialId, true), true)
                    }
                    className="inline-flex h-9 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
                  >
                    <RotateCcw size={13} />
                    {t("Start over")}
                  </button>
                </div>
                <button
                  type="button"
                  disabled={busy || !summaryReady || !reflectionReady}
                  onClick={() => void submit()}
                  className="inline-flex h-9 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-xs font-semibold text-[var(--primary-foreground)] disabled:opacity-45"
                >
                  {busy && <Loader2 size={13} className="animate-spin" />}
                  {t("Submit Focus-Check")}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

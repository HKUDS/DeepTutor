"use client";

/**
 * Read-only practice view a guardian (or admin) opens via
 * `/learning/practice?learner=<id>` (#1988). Reads only: the banner says so,
 * no import/review controls are rendered, and the write endpoints reject a
 * learner scope server-side regardless of what this UI does.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarCheck, EyeOff, Loader2 } from "lucide-react";
import { getGuardianReport, type GuardianReport } from "@/lib/guardian-api";
import {
  getPracticeQuestion,
  getPracticeQueue,
  getPracticeSummary,
  type PracticeQuestion,
  type PracticeSummary,
} from "@/lib/practice-api";
import { LearningErrorState, LearningShell } from "../LearningShell";
import { PracticeInsights } from "./PracticeInsights";

export function GuardianPracticeView({ learnerId }: { learnerId: string }) {
  const { t } = useTranslation();
  const [report, setReport] = useState<GuardianReport | null>(null);
  const [summary, setSummary] = useState<PracticeSummary | null>(null);
  const [queue, setQueue] = useState<PracticeQuestion[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<PracticeQuestion | null>(null);
  const [detailError, setDetailError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextReport, nextSummary, nextQueue] = await Promise.all([
        getGuardianReport(learnerId),
        getPracticeSummary("", undefined, learnerId),
        getPracticeQueue("", undefined, learnerId),
      ]);
      setReport(nextReport);
      setSummary(nextSummary);
      setQueue(nextQueue);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [learnerId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function openDetail(id: number) {
    setDetailError("");
    setDetail(null);
    try {
      setDetail(await getPracticeQuestion(id, undefined, learnerId));
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err));
    }
  }

  const learnerName = report?.learner.username || learnerId;
  return (
    <LearningShell
      title={t("Practice")}
      subtitle={t("Read-only view of a learner's practice.")}
    >
      <div
        role="note"
        className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm"
      >
        <EyeOff size={18} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
        <div>
          <p className="font-medium">
            {t("{{name}}'s practice — read-only", { name: learnerName })}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {t(
              "You are viewing this learner's practice in read-only mode. Answering and reviewing stay with the learner."
            )}
          </p>
        </div>
      </div>
      {loading && !summary ? (
        <div role="status" className="flex h-40 items-center justify-center text-muted-foreground">
          <Loader2 size={18} className="mr-2 animate-spin" />
          {t("Loading…")}
        </div>
      ) : error ? (
        <LearningErrorState
          message={t("Could not open this learner's practice.") + (error ? ` (${error})` : "")}
          onRetry={() => void refresh()}
        />
      ) : (
        <>
          <section
            aria-labelledby="guardian-practice-today"
            className="mb-7 rounded-2xl border border-border bg-card p-5 sm:p-6"
          >
            <div className="flex items-start gap-4">
              <div className="rounded-xl bg-emerald-500/10 p-3 text-emerald-600 dark:text-emerald-400">
                <CalendarCheck size={22} />
              </div>
              <div>
                <h2 id="guardian-practice-today" className="text-base font-semibold">
                  {t("Today's review")}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {summary
                    ? summary.due > 0
                      ? t("{{count}} questions are ready to revisit.", { count: summary.due })
                      : t("You are caught up. Come back when your next reviews are due.")
                    : t("Loading…")}
                </p>
                {summary && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t("{{done}} reviewed today · {{overdue}} overdue", {
                      done: summary.reviewed_today,
                      overdue: summary.overdue,
                    })}
                  </p>
                )}
              </div>
            </div>
          </section>
          <PracticeInsights courseId="" revision={0} learnerId={learnerId} />
          <section aria-labelledby="guardian-due-list" className="mt-2">
            <h2 id="guardian-due-list" className="mb-3 text-sm font-semibold">
              {t("Due questions")}
            </h2>
            {detailError && <LearningErrorState message={detailError} />}
            {queue.length ? (
              <ul className="divide-y divide-border rounded-2xl border border-border bg-card">
                {queue.map(item => (
                  <li key={item.entry.id}>
                    <button
                      type="button"
                      onClick={() => void openDetail(item.entry.id)}
                      className="flex w-full items-start justify-between gap-3 p-4 text-left text-sm hover:bg-muted/50"
                      aria-expanded={detail?.entry.id === item.entry.id}
                    >
                      <span className="min-w-0">
                        {item.entry.question}
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {item.entry.source}
                        </span>
                      </span>
                      {item.state.is_mistake && (
                        <span className="shrink-0 rounded-full bg-orange-500/10 px-2 py-0.5 text-xs text-orange-600 dark:text-orange-400">
                          {t("Mistake")}
                        </span>
                      )}
                    </button>
                    {detail?.entry.id === item.entry.id && (
                      <div className="border-t border-border bg-muted/20 p-4 text-sm">
                        <p className="font-medium">{detail.entry.question}</p>
                        {detail.entry.options &&
                          Object.keys(detail.entry.options).length > 0 && (
                            <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                              {Object.entries(detail.entry.options).map(([key, value]) => (
                                <li key={key}>
                                  <span className="font-medium text-foreground">{key}.</span>{" "}
                                  {String(value)}
                                </li>
                              ))}
                            </ul>
                          )}
                        <p className="mt-3 text-xs">
                          <span className="font-medium">{t("Correct answer")}:</span>{" "}
                          {detail.entry.correct_answer}
                        </p>
                        {detail.entry.explanation && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            <span className="font-medium text-foreground">{t("Explanation")}:</span>{" "}
                            {detail.entry.explanation}
                          </p>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              !detailError && (
                <p className="rounded-2xl border border-border bg-card p-4 text-sm text-muted-foreground">
                  {t("No questions are due right now.")}
                </p>
              )
            )}
          </section>
        </>
      )}
    </LearningShell>
  );
}

"use client";

import { Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ObjectiveReport } from "@/lib/learning-api";

import { formatAbsolute, formatRelative, type Translate } from "./format";

/**
 * The evidence behind one objective.
 *
 * The map answers "am I through the gate"; this answers "why" — which
 * questions were asked, what the learner said, what the engine did with it,
 * and when it comes back for review. The gate itself is shown as a bar with
 * the threshold marked, because a hard gate is only legible if you can see how
 * far away it is.
 */
export function ObjectiveDetail({
  report,
  zh,
}: {
  report: ObjectiveReport;
  zh: boolean;
}) {
  const { t } = useTranslation();
  const qualitative = report.gate === "qualitative";
  return (
    <div className="mt-1 mb-2 ml-5 space-y-3 border-l border-[var(--border)] pl-3">
      <GateBar report={report} />

      {report.review && (
        <Row label={t("Spaced review")}>
          {report.review.due_at
            ? t("Due {{relative}} · {{absolute}}", {
                relative: formatRelative(report.review.due_at, zh),
                absolute: formatAbsolute(report.review.due_at, zh),
              })
            : t("Not scheduled")}
          <span className="ml-2 text-[var(--muted-foreground)]">
            {t("interval {{interval}} · {{streak}} in a row", {
              interval: report.review.interval_index + 1,
              streak: report.review.consecutive_correct,
            })}
          </span>
        </Row>
      )}

      {qualitative && report.explanation && (
        <Row label={t("Your explanation")}>
          <span className="italic">{report.explanation}</span>
        </Row>
      )}

      {report.attempts.length > 0 && (
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">
            {t("Attempts ({{correct}}/{{total}} correct)", {
              correct: report.correct_count,
              total: report.attempts.length,
            })}
          </div>
          <ul className="mt-1 space-y-1.5">
            {[...report.attempts].reverse().map((attempt, index) => (
              <li
                key={`${attempt.question_id}-${index}`}
                className="flex gap-2 text-xs"
              >
                {attempt.is_correct ? (
                  <Check className="mt-0.5 h-3 w-3 shrink-0 text-green-500" />
                ) : (
                  <X className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />
                )}
                <div className="min-w-0">
                  <div className="text-[var(--foreground)]">
                    {attempt.prompt || t("(prompt unavailable)")}
                  </div>
                  <div className="text-[var(--muted-foreground)]">
                    {t("You said: ")}
                    {attempt.answer || t("(blank)")}
                    <span className="ml-2">
                      {formatRelative(attempt.at, zh)}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.errors.length > 0 && (
        <Row label={t("Error diagnosis")}>
          {report.errors.map((record) => (
            <span key={record.id} className="mr-2">
              {t(record.error_type)}
              {record.retries > 0 &&
                t(" · {{count}} retries", { count: record.retries })}
              {record.status === "graduated" && t(" · cleared")}
            </span>
          ))}
        </Row>
      )}

      {report.attempts.length === 0 && !report.explanation && (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t(
            "No attempts yet. Once you work through this waypoint, its questions, your answers, and the grading evidence will appear here.",
          )}
        </p>
      )}
    </div>
  );
}

/** Mastery against the gate it has to clear. */
function GateBar({ report }: { report: ObjectiveReport }) {
  const { t } = useTranslation();
  const pct = Math.round(report.mastery * 100);
  const thresholdPct = Math.round(report.threshold * 100);
  const perfectButBelowGate =
    report.gate === "quantitative" &&
    report.attempts.length > 0 &&
    report.correct_count === report.attempts.length &&
    report.mastery < report.threshold;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-[var(--muted-foreground)]">
          {report.gate === "qualitative"
            ? t("Qualitative gate: explain it in your own words")
            : t("Quantitative gate: {{pct}}%", { pct: thresholdPct })}
        </span>
        <span
          className={
            report.mastered
              ? "text-green-500"
              : "text-[var(--muted-foreground)]"
          }
        >
          {pct}%
        </span>
      </div>
      <div className="relative mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[var(--accent)]">
        <div
          className={`h-full ${report.mastered ? "bg-[var(--primary)]" : "bg-[var(--muted-foreground)]"}`}
          style={{ width: `${pct}%` }}
        />
        {report.gate === "quantitative" && (
          <div
            className="absolute inset-y-0 w-px bg-[var(--foreground)]/40"
            style={{ left: `${thresholdPct}%` }}
          />
        )}
      </div>
      {perfectButBelowGate && (
        <p className="mt-1.5 text-[11px] leading-4 text-[var(--muted-foreground)]">
          {t(
            "Even with {{correct}}/{{total}} correct so far, mastery also weighs evidence volume, difficulty, and recent consistency. One more discriminating practice can raise it further.",
            { correct: report.correct_count, total: report.attempts.length },
          )}
        </p>
      )}
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="text-xs">
      <div className="text-[var(--muted-foreground)]">{label}</div>
      <div className="mt-0.5 text-[var(--foreground)]">{children}</div>
    </div>
  );
}

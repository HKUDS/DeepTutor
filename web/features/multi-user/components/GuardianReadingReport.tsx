"use client";

import { useTranslation } from "react-i18next";
import type { GuardianReadingSummary } from "@/lib/guardian-api";

export function GuardianReadingReport({ reading }: { reading: GuardianReadingSummary }) {
  const { t } = useTranslation();
  const titles = new Map(reading.quizzes.map(item => [item.material_id, item.material_title]));
  return (
    <section aria-label={t("Reading progress and quiz records")} className="space-y-3 rounded-lg border border-[var(--border)] p-4">
      <h3 className="text-sm font-medium">{t("Reading progress and quiz records")}</h3>
      <p className="text-xs text-[var(--muted-foreground)]">{t("Reading position and quiz results do not establish independent mastery.")}</p>
      {reading.reading_status === "available" ? <>
      <p className="text-xs">{t("Showing {{shown}} of {{total}} reading records", { shown: reading.progress.length, total: reading.progress_total })}</p>
      <ul className="space-y-2 text-sm">
        {reading.progress.map(item => (
          <li key={item.material_id}>
            <span>{item.material_title || titles.get(item.material_id) || t("Reading material {{id}}", { id: item.material_id })}</span>{" · "}
            {t("Current section {{section}} · furthest position {{percent}}%", { section: item.latest_locator, percent: Math.round(item.furthest_percentage * 100) })}
          </li>
        ))}
      </ul>
      <p className="text-xs text-[var(--muted-foreground)]">{t("Recent reading activities: {{count}} (up to {{limit}})", { count: reading.activities.length, limit: reading.limit })}</p>
      </> : <p className="text-sm">{reading.reading_status === "migration_required" ? t("Reading records need migration before they can be reported. Viewing this report does not migrate them.") : t("Reading records have not been initialized.")}</p>}
      {reading.quiz_status === "available" ? <>
      <p className="text-xs">{t("Showing {{shown}} of {{total}} quiz records", { shown: reading.quizzes.length, total: reading.quiz_total })}</p>
      <ul className="space-y-3 text-sm">
        {reading.quizzes.map(item => (
          <li key={item.id} className="border-t border-[var(--border)] pt-2">
            <p>{item.question}</p>
            <p className="text-xs text-[var(--muted-foreground)]">
              {item.is_correct === null ? t("Not graded") : item.is_correct ? t("Correct") : t("Incorrect")}{" · "}
              {t("{{count}} attempts", { count: item.attempt_count })}{" · "}
              {item.hints_used > 0 ? t("{{count}} recorded hints", { count: item.hints_used }) : t("No question-linked help recorded")}
            </p>
          </li>
        ))}
      </ul>
      </> : <p className="text-sm">{reading.quiz_status === "migration_required" ? t("Quiz records need migration before they can be reported. Viewing this report does not migrate them.") : t("Quiz records have not been initialized.")}</p>}
    </section>
  );
}

"use client";

import { useTranslation } from "react-i18next";
import type { KnowledgeImportReport } from "@/features/knowledge/api/files";

interface KbImportSummaryProps {
  /** KB paths the upload stored as new files. */
  files: string[];
  report?: KnowledgeImportReport;
}

/**
 * Per-file outcome of an archive upload. Re-importing an updated course
 * download stores only what changed; this says what was skipped as identical,
 * which changed files were kept beside the existing version, and which
 * members were not imported, instead of leaving the user to guess.
 */
export default function KbImportSummary({
  files,
  report,
}: KbImportSummaryProps) {
  const { t } = useTranslation();
  if (
    !report ||
    (!report.duplicates.length &&
      !report.renamed.length &&
      !report.rejected.length)
  ) {
    return null;
  }

  return (
    <div
      role="status"
      className="space-y-1.5 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2 text-[12px] text-[var(--muted-foreground)]"
    >
      <div>{t("New files: {{count}}", { count: files.length })}</div>
      {report.duplicates.length > 0 && (
        <div>
          {t(
            "Identical files already in this knowledge base, skipped: {{count}}",
            {
              count: report.duplicates.length,
            },
          )}
        </div>
      )}
      {report.renamed.length > 0 && (
        <div>
          <div className="text-amber-700 dark:text-amber-300">
            {t("Changed files stored next to the existing version: {{count}}", {
              count: report.renamed.length,
            })}
          </div>
          <ul className="mt-0.5 list-disc pl-4 font-mono text-[11px]">
            {report.renamed.map((item) => (
              <li key={item.path}>{`${item.path} ← ${item.conflicts_with}`}</li>
            ))}
          </ul>
        </div>
      )}
      {report.rejected.length > 0 && (
        <div>
          <div className="text-red-700 dark:text-red-300">
            {t("Not imported (unsupported or unsafe): {{count}}", {
              count: report.rejected.length,
            })}
          </div>
          <ul className="mt-0.5 list-disc pl-4 font-mono text-[11px]">
            {report.rejected.map((item) => (
              <li key={item.file}>{`${item.file} — ${item.reason}`}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

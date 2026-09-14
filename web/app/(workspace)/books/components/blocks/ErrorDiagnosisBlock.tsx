"use client";

import { Stethoscope } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Block } from "@/lib/book-types";

interface Diagnosis {
  kp_id?: string;
  kp_name?: string;
  error_type?: string;
  error_label?: string;
  count?: number;
  advice?: string;
}

export interface ErrorDiagnosisBlockProps {
  block: Block;
}

export default function ErrorDiagnosisBlock({ block }: ErrorDiagnosisBlockProps) {
  const { t } = useTranslation();
  const diagnoses =
    (block.payload?.diagnoses as Diagnosis[] | undefined) || [];
  const guidance = String(block.payload?.guidance ?? "").trim();

  if (diagnoses.length === 0) return null;

  const busiest = Math.max(
    ...diagnoses.map((d) => (typeof d.count === "number" ? d.count : 0)),
    1,
  );

  return (
    <div className="rounded-2xl border border-amber-300/60 bg-gradient-to-br from-amber-500/5 to-transparent p-4 shadow-sm dark:border-amber-500/40">
      <div className="mb-3 flex items-center gap-2">
        <Stethoscope className="h-4 w-4 text-amber-600 dark:text-amber-400" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-400">
          {t("Error Diagnosis")}
        </span>
      </div>
      {guidance && (
        <p className="mb-3 text-sm leading-relaxed text-[var(--foreground)]">
          {guidance}
        </p>
      )}
      <ul className="space-y-2">
        {diagnoses.map((d, i) => (
          <li
            key={d.kp_id || i}
            className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-[var(--foreground)]">
                {d.kp_name || d.kp_id || t("Review")}
              </span>
              {typeof d.count === "number" && (
                <span
                  // Bar length encodes how often this point went wrong, so the
                  // learner can see at a glance what to tackle first.
                  className="relative rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-400"
                  style={{
                    minWidth: `${Math.round(28 + 36 * (d.count / busiest))}px`,
                    textAlign: "center",
                  }}
                >
                  ×{d.count}
                </span>
              )}
            </div>
            {d.error_label && (
              <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                {d.error_label}
              </div>
            )}
            {d.advice && (
              <div className="mt-1.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
                {d.advice}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

"use client";

import { CheckCircle2, FileWarning, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TopicCoverage } from "@/lib/learning-api";

/**
 * Whether the generated outline accounted for every document selected.
 *
 * A route over a twenty-document library used to be built from four retrieved
 * passages, so it covered whatever retrieval happened to match and quietly
 * ignored the rest — with nothing on screen to say so. The outline now names
 * the materials each region is built from, and this is where that becomes
 * visible: what was left out, and one button to ask for it.
 *
 * Three states, and the third is the reason this component is not a one-liner:
 * a model that named no materials at all has told us nothing, and listing
 * every document as "missed" would send the learner regenerating an outline
 * that may well already be complete. Silence is the honest rendering there.
 */
export function CoverageNotice({
  coverage,
  busy,
  onCover,
}: {
  coverage: TopicCoverage | undefined;
  busy: boolean;
  onCover: (documents: string[]) => void;
}) {
  const { t } = useTranslation();
  if (!coverage || coverage.documents === 0 || !coverage.reported) return null;

  const missing = coverage.missing;
  if (missing.length === 0) {
    return (
      <div className="mb-4 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
        <CheckCircle2 className="h-3.5 w-3.5 text-[var(--success)]" />
        {`${t("Every one of your")} ${coverage.documents} ${t("files has a place in this outline")}`}
      </div>
    );
  }

  return (
    <div className="mb-4 rounded-xl border border-[color-mix(in_srgb,var(--warning)_35%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,transparent)] p-3">
      <div className="flex items-start gap-2">
        <FileWarning className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium text-[var(--foreground)]">
            {`${missing.length} ${t("of your files did not make it into this outline")}`}
          </div>
          {/* Named, not counted: which files were dropped decides whether this
              matters — a leftover syllabus is fine, a missing chapter is not. */}
          <ul className="mt-1.5 space-y-0.5">
            {missing.slice(0, 8).map((gap) => (
              <li
                key={`${gap.label}:${gap.document}`}
                className="truncate text-[11.5px] text-[var(--muted-foreground)]"
              >
                {gap.document}
                <span className="text-[color-mix(in_srgb,var(--muted-foreground)_70%,transparent)]">
                  {` · ${gap.label}`}
                </span>
              </li>
            ))}
            {missing.length > 8 && (
              <li className="text-[11.5px] text-[var(--muted-foreground)]">
                {`+${missing.length - 8} ${t("more")}`}
              </li>
            )}
          </ul>
          <button
            type="button"
            onClick={() => onCover(missing.map((gap) => gap.document))}
            disabled={busy}
            className="mt-2.5 inline-flex items-center gap-1.5 rounded-full bg-[var(--primary)] px-3 py-1.5 text-[11.5px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90 disabled:opacity-50"
          >
            {busy && <Loader2 className="h-3 w-3 animate-spin" />}
            {t("Regenerate covering these too")}
          </button>
          <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Or leave them out — you can also edit the outline directly below.",
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

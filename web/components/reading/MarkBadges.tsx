"use client";

import { AlertCircle, Bookmark, Bot } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AnnotationItem } from "@/lib/reading-api";

/**
 * The small status badges under a mark's text.
 *
 * Split out of the row so the row does not carry five independent predicates
 * inline; each badge is its own condition and none of them interacts.
 */
export function MarkBadges({ annotation }: { annotation: AnnotationItem }) {
  const { t } = useTranslation();
  const resolution = annotation.resolution;
  return (
    <div className="mt-1 flex items-center gap-1.5 pl-1.5">
      {annotation.author === "assistant" && (
        <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] px-1.5 py-[1px] text-[10px] font-medium text-[var(--primary)]">
          <Bot size={9} />
          {t("AI")}
        </span>
      )}
      {annotation.kind === "underline" && (
        <span className="text-[10px] text-[var(--muted-foreground)]">
          {t("Underline")}
        </span>
      )}
      {annotation.kind === "citation" && (
        <span className="inline-flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
          <Bookmark size={9} />
          {t("Citation")}
        </span>
      )}
      {resolution === "unresolved" && (
        <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--destructive)_8%,transparent)] px-1.5 py-[1px] text-[10px] font-medium text-[var(--destructive)]">
          <AlertCircle size={9} />
          {t("Not found")}
        </span>
      )}
      {resolution === "ambiguous" && (
        <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--warning,oklch(0.78_0.16_70))_10%,transparent)] px-1.5 py-[1px] text-[10px] font-medium text-[var(--warning,oklch(0.62_0.16_45))]">
          <AlertCircle size={9} />
          {t("Ambiguous")}
        </span>
      )}
    </div>
  );
}

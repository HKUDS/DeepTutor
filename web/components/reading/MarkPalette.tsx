"use client";

import { useTranslation } from "react-i18next";

import {
  ANNOTATION_COLORS,
  ANNOTATION_SWATCH,
  annotationColorLabel,
  type AnnotationItem,
} from "@/lib/reading-api";

/**
 * The palette and the kind toggle under a mark.
 *
 * Split out of the row: five swatches plus a kind switch is six controls with
 * their own pressed/disabled state, and none of it is the row's business.
 */
export function MarkPalette({
  annotation,
  busy,
  onRecolour,
  onChangeKind,
}: {
  annotation: AnnotationItem;
  busy: boolean;
  onRecolour: (annotation: AnnotationItem, color: string) => void;
  onChangeKind: (annotation: AnnotationItem, kind: AnnotationItem["kind"]) => void;
}) {
  const { t } = useTranslation();
  const isUnderline = annotation.kind === "underline";
  return (
    <div
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
      role="group"
      aria-label={t("Change colour")}
      className="mt-1.5 flex items-center gap-1 pl-1.5"
    >
      {ANNOTATION_COLORS.map((swatch) => (
        <button
          key={swatch}
          type="button"
          aria-label={t(annotationColorLabel(swatch))}
          aria-pressed={annotation.color === swatch}
          disabled={busy}
          onClick={() => onRecolour(annotation, swatch)}
          className={`h-3.5 w-3.5 rounded-full border transition disabled:opacity-40 ${
            annotation.color === swatch
              ? "border-[var(--foreground)] scale-110"
              : "border-black/10 hover:scale-105"
          }`}
          style={{ background: ANNOTATION_SWATCH[swatch] }}
        />
      ))}
      {annotation.kind !== "citation" && (
        <>
          <span className="mx-0.5 h-3 w-px bg-[var(--border)]" aria-hidden />
          <button
            type="button"
            aria-label={t(isUnderline ? "Highlight" : "Underline")}
            disabled={busy}
            onClick={() =>
              onChangeKind(annotation, isUnderline ? "highlight" : "underline")
            }
            className="inline-flex h-4 items-center rounded px-1 text-[9.5px] font-medium text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
          >
            {t(isUnderline ? "Highlight" : "Underline")}
          </button>
        </>
      )}
    </div>
  );
}

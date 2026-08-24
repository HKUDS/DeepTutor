"use client";

import { useMemo } from "react";
import { Bot, Sparkles, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AnnotationItem, UnitKind } from "@/lib/reading-api";
import { unitLabel } from "./TextUnitView";

const SWATCH: Record<string, string> = {
  yellow: "#facd5a",
  green: "#8cdb94",
  blue: "#7ac0fa",
  pink: "#faa1c7",
  purple: "#c7aefa",
};

export interface AnnotationListProps {
  annotations: AnnotationItem[];
  unit: UnitKind;
  activeId: string | null;
  onSelect: (annotation: AnnotationItem) => void;
  onDelete: (annotation: AnnotationItem) => void;
}

/**
 * The marks made on this material, grouped by locator.
 *
 * Grouped rather than flat because a reader thinks in "what did I mark on page
 * 12", and because it makes the assistant's own marks legible in context next to
 * the user's own.
 */
export function AnnotationList({
  annotations,
  unit,
  activeId,
  onSelect,
  onDelete,
}: AnnotationListProps) {
  const { t } = useTranslation();

  const groups = useMemo(() => {
    const byLocator = new Map<number, AnnotationItem[]>();
    for (const annotation of annotations) {
      const bucket = byLocator.get(annotation.locator) ?? [];
      bucket.push(annotation);
      byLocator.set(annotation.locator, bucket);
    }
    return [...byLocator.entries()].sort((a, b) => a[0] - b[0]);
  }, [annotations]);

  if (!annotations.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
        <Sparkles size={18} className="text-[var(--muted-foreground)]/60" />
        <p className="text-[12px] font-medium text-[var(--foreground)]">
          {t("No annotations yet")}
        </p>
        <p className="max-w-[220px] text-[11px] leading-relaxed text-[var(--muted-foreground)]">
          {t("Select text in the document to highlight it or attach a note.")}
        </p>
      </div>
    );
  }

  return (
    <div className="dt-reader-scroll h-full overflow-y-auto px-2.5 py-2">
      {groups.map(([locator, rows]) => (
        <section key={locator} className="mb-3 last:mb-1">
          <h4 className="sticky top-0 z-10 mb-1 bg-[var(--background)]/95 px-1 py-1 font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--muted-foreground)] backdrop-blur">
            {t(unitLabel(unit))} {locator}
          </h4>
          <ul className="space-y-1">
            {rows.map((annotation) => (
              <li key={annotation.annotation_id}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect(annotation)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(annotation);
                    }
                  }}
                  className={`group/anno relative w-full cursor-pointer rounded-lg border px-2.5 py-2 text-left transition ${
                    annotation.annotation_id === activeId
                      ? "border-[var(--ring)] bg-[var(--muted)]/60"
                      : "border-transparent hover:border-[var(--border)] hover:bg-[var(--muted)]/40"
                  }`}
                >
                  <span
                    aria-hidden
                    className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full"
                    style={{
                      background: SWATCH[annotation.color] ?? SWATCH.yellow,
                    }}
                  />
                  {annotation.quote && (
                    <p className="line-clamp-3 pl-1.5 text-[12px] leading-[1.55] text-[var(--foreground)]">
                      {annotation.quote}
                    </p>
                  )}
                  {annotation.note && (
                    <p className="mt-1 line-clamp-3 pl-1.5 text-[11px] leading-[1.5] text-[var(--muted-foreground)]">
                      {annotation.note}
                    </p>
                  )}
                  <div className="mt-1 flex items-center gap-1.5 pl-1.5">
                    {annotation.author === "assistant" && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[var(--primary)]/10 px-1.5 py-[1px] text-[10px] font-medium text-[var(--primary)]">
                        <Bot size={9} />
                        {t("AI")}
                      </span>
                    )}
                    {annotation.kind === "underline" && (
                      <span className="text-[10px] text-[var(--muted-foreground)]">
                        {t("Underline")}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    title={t("Delete annotation")}
                    aria-label={t("Delete annotation")}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(annotation);
                    }}
                    className="absolute right-1.5 top-1.5 inline-flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--destructive)]/10 hover:text-[var(--destructive)] focus-visible:opacity-100 group-hover/anno:opacity-100"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

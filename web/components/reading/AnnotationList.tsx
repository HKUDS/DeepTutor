"use client";

import { useMemo, useState } from "react";
import { Bookmark, Bot, Highlighter, Sparkles, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  ANNOTATION_SWATCH,
  type AnnotationColor,
  type AnnotationItem,
  type UnitKind,
} from "@/lib/reading-api";
import { unitLabel } from "./TextUnitView";

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
 * Citations deliberately share the annotation store, selectors and source
 * positions. The tab is only a filtered view: it does not create a second
 * persistence model that could drift from the document's other marks.
 */
export function AnnotationList({
  annotations,
  unit,
  activeId,
  onSelect,
  onDelete,
}: AnnotationListProps) {
  const { t } = useTranslation();
  const [view, setView] = useState<"annotations" | "citations">("annotations");

  const visibleAnnotations = useMemo(
    () =>
      annotations.filter((annotation) =>
        view === "citations"
          ? annotation.kind === "citation"
          : annotation.kind !== "citation",
      ),
    [annotations, view],
  );

  const groups = useMemo(() => {
    const byLocator = new Map<number, AnnotationItem[]>();
    for (const annotation of visibleAnnotations) {
      const bucket = byLocator.get(annotation.locator) ?? [];
      bucket.push(annotation);
      byLocator.set(annotation.locator, bucket);
    }
    return [...byLocator.entries()].sort((a, b) => a[0] - b[0]);
  }, [visibleAnnotations]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        role="tablist"
        aria-label={t("Saved reading marks")}
        className="grid shrink-0 grid-cols-2 gap-1 border-b border-[var(--border)] p-2"
      >
        <ViewTab
          active={view === "annotations"}
          icon={Highlighter}
          label={t("Annotations")}
          onClick={() => setView("annotations")}
        />
        <ViewTab
          active={view === "citations"}
          icon={Bookmark}
          label={t("Citations")}
          onClick={() => setView("citations")}
        />
      </div>

      {!visibleAnnotations.length ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <Sparkles size={18} className="text-[color-mix(in_srgb,var(--muted-foreground)_60%,transparent)]" />
          <p className="text-[12px] font-medium text-[var(--foreground)]">
            {t(
              view === "citations" ? "No citations yet" : "No annotations yet",
            )}
          </p>
          <p className="max-w-[220px] text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              view === "citations"
                ? "Select text in the document to save a citation."
                : "Select text in the document to highlight it or attach a note.",
            )}
          </p>
        </div>
      ) : (
        <div className="dt-reader-scroll min-h-0 flex-1 overflow-y-auto px-2.5 py-2">
          {groups.map(([locator, rows]) => (
            <section key={locator} className="mb-3 last:mb-1">
              <h4 className="sticky top-0 z-10 mb-1 bg-[color-mix(in_srgb,var(--background)_95%,transparent)] px-1 py-1 font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--muted-foreground)] backdrop-blur">
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
                          ? "border-[var(--ring)] bg-[color-mix(in_srgb,var(--muted)_60%,transparent)]"
                          : "border-transparent hover:border-[var(--border)] hover:bg-[color-mix(in_srgb,var(--muted)_40%,transparent)]"
                      }`}
                    >
                      <span
                        aria-hidden
                        className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full"
                        style={{
                          background:
                            ANNOTATION_SWATCH[
                              annotation.color as AnnotationColor
                            ] ?? ANNOTATION_SWATCH.yellow,
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
                      </div>
                      <button
                        type="button"
                        title={t("Delete annotation")}
                        aria-label={t("Delete annotation")}
                        onClick={(event) => {
                          event.stopPropagation();
                          onDelete(annotation);
                        }}
                        className="absolute right-1.5 top-1.5 inline-flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-0 transition hover:bg-[color-mix(in_srgb,var(--destructive)_10%,transparent)] hover:text-[var(--destructive)] focus-visible:opacity-100 group-hover/anno:opacity-100"
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
      )}
    </div>
  );
}

function ViewTab({
  active,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: typeof Highlighter;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`inline-flex min-w-0 items-center justify-center gap-1 rounded-lg px-2 py-1.5 text-[11px] font-medium transition ${
        active
          ? "bg-[var(--muted)] text-[var(--foreground)]"
          : "text-[var(--muted-foreground)] hover:bg-[color-mix(in_srgb,var(--muted)_60%,transparent)] hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={12} />
      <span className="truncate">{label}</span>
    </button>
  );
}

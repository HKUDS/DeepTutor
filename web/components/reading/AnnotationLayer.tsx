"use client";

import type { AnnotationItem, NormalisedRect } from "@/lib/reading-api";

/** Ink for each palette colour, tuned to stay readable over black-on-white text. */
const COLOR_INK: Record<string, string> = {
  yellow: "250 220 90",
  green: "140 219 148",
  blue: "122 192 250",
  pink: "250 161 199",
  purple: "199 174 250",
};

function ink(color: string): string {
  return COLOR_INK[color] ?? COLOR_INK.yellow;
}

export interface AnnotationLayerProps {
  annotations: AnnotationItem[];
  highlightedAnnotationId?: string | null;
  flashRects?: NormalisedRect[];
  onAnnotationClick?: (annotation: AnnotationItem) => void;
}

/**
 * Overlay that paints stored marks over one rendered unit.
 *
 * Positioned entirely in percentages from the annotation's normalised rects, so
 * it needs no measurement and stays correct through zoom and pane resizing.
 *
 * `multiply` blending is what makes a highlight look like a highlighter rather
 * than a coloured box on top of the words: the text below stays fully legible
 * instead of being tinted.
 *
 * The layer itself is click-through (`pointer-events-none`); only the marks take
 * clicks, so highlighting never blocks text selection on the layer beneath.
 */
export function AnnotationLayer({
  annotations,
  highlightedAnnotationId,
  flashRects,
  onAnnotationClick,
}: AnnotationLayerProps) {
  return (
    <div className="pointer-events-none absolute inset-0">
      {annotations.map((annotation) =>
        annotation.rects.map((rect, index) => {
          const [x0, y0, x1, y1] = rect;
          const isFocused =
            annotation.annotation_id === highlightedAnnotationId;
          const isUnderline = annotation.kind === "underline";
          return (
            <button
              key={`${annotation.annotation_id}-${index}`}
              type="button"
              title={annotation.note || annotation.quote || undefined}
              onClick={() => onAnnotationClick?.(annotation)}
              className={[
                "pointer-events-auto absolute cursor-pointer transition-[box-shadow,filter] duration-150",
                isUnderline ? "" : "mix-blend-multiply",
                isFocused ? "ring-2 ring-[var(--ring)] ring-offset-1" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${Math.max(0, x1 - x0) * 100}%`,
                height: `${Math.max(0, y1 - y0) * 100}%`,
                background: isUnderline
                  ? undefined
                  : `rgb(${ink(annotation.color)} / ${isFocused ? 0.85 : 0.6})`,
                borderBottom: isUnderline
                  ? `2px solid rgb(${ink(annotation.color)})`
                  : undefined,
                borderRadius: isUnderline ? 0 : 2,
              }}
            >
              {annotation.author === "assistant" && index === 0 && (
                <span
                  aria-hidden
                  className="absolute -top-1 -right-1 h-1.5 w-1.5 rounded-full bg-[var(--primary)] shadow-sm"
                />
              )}
            </button>
          );
        }),
      )}
      {(flashRects ?? []).map((rect, index) => {
        const [x0, y0, x1, y1] = rect;
        return (
          <span
            key={`flash-${index}`}
            aria-hidden
            className="dt-reader-flash absolute rounded-[2px]"
            style={{
              left: `${x0 * 100}%`,
              top: `${y0 * 100}%`,
              width: `${Math.max(0, x1 - x0) * 100}%`,
              height: `${Math.max(0, y1 - y0) * 100}%`,
            }}
          />
        );
      })}
    </div>
  );
}

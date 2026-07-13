"use client";

import { memo, useState } from "react";
import { ChevronDown, X, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * One row in the reference tree: an attachment, a Space reference, a
 * persona, etc. All kinds render identically (monochrome icon + kind
 * prefix + label) — visual uniformity is the point.
 */
export interface ContextTreeItem {
  key: string;
  // A lucide icon, or any glyph with the same call signature (brand SVG marks
  // are cast to this at the call site).
  icon: LucideIcon;
  /** Type prefix ("Book", "Notebook", ...), already translated. */
  kind: string;
  /** Item title; truncates. */
  label: string;
  /** 16px thumbnail for image attachments — replaces the icon. */
  thumbnailUrl?: string;
  /** Optional click action (e.g. open attachment preview). */
  onClick?: () => void;
  /** Optional remove action (composer only). */
  onRemove?: () => void;
}

/**
 * Connector glyph: a thin rounded elbow line (NOT a bordered box — that
 * reads as a todo checkbox). Drawn for the "up" flavor (┌: rises from
 * the textarea, turns right); the mirrored/down flavors derive from it
 * via CSS transforms.
 */
function ElbowMark({
  direction,
  mirrored,
}: {
  direction: "up" | "down";
  mirrored: boolean;
}) {
  const flip = [
    direction === "down" ? "-scale-y-100" : "",
    mirrored ? "-scale-x-100" : "",
  ]
    .join(" ")
    .trim();
  return (
    <svg
      aria-hidden
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      className={`mt-[3.5px] shrink-0 self-start text-[var(--muted-foreground)]/45 ${flip}`}
    >
      {/* vertical arm from the box edge, rounded corner, horizontal arm */}
      <path
        d="M2 11 V6 Q2 3 5 3 H11"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * Folded-content mark for the summary toggle: three quiet dots — the
 * "…" idiom for collapsed lines. The toggle is a control, not a ref,
 * so it gets no elbow; once expanded nothing is hidden anymore and the
 * mark yields to a blank spacer that keeps the text column aligned.
 */
function FoldMark({ visible }: { visible: boolean }) {
  return (
    <svg
      aria-hidden
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      className="shrink-0 text-[var(--muted-foreground)]/55"
    >
      {visible && (
        <>
          <circle cx="2.2" cy="6" r="1.1" fill="currentColor" />
          <circle cx="6" cy="6" r="1.1" fill="currentColor" />
          <circle cx="9.8" cy="6" r="1.1" fill="currentColor" />
        </>
      )}
    </svg>
  );
}

/**
 * Claude-Code-style attachment tree: an elbow connector + a quiet
 * collapsed summary ("N references"), expandable to one row per item.
 *
 * direction="up" is the composer flavor — the block sits above the
 * textarea and the elbows read as the input box extending upward.
 * direction="down" + align="right" is the sent-message flavor: ┘
 * elbows hug the bubble's right edge and the rows extend leftward.
 */
export default memo(function ContextReferenceTree({
  items,
  direction,
  align = "left",
  summaryNoun,
}: {
  items: ContextTreeItem[];
  direction: "up" | "down";
  align?: "left" | "right";
  /** Translated noun for the collapsed summary ("attachments" / "references"). */
  summaryNoun: string;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;

  // A single item needs no collapse ceremony — show it directly.
  const collapsible = items.length > 1;
  const showRows = !collapsible || expanded;
  const mirrored = align === "right";
  const alignClass = mirrored ? "items-end" : "items-start";
  // Mirrored rows reverse the flex order so the elbow sits at the right
  // edge (hugging the bubble) and content extends leftward.
  const rowDirClass = mirrored ? "flex-row-reverse" : "";

  const rows = showRows
    ? items.map((item) => {
        const Inner = (
          <>
            <ElbowMark direction={direction} mirrored={mirrored} />
            {item.thumbnailUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={item.thumbnailUrl}
                alt=""
                aria-hidden
                className="h-4 w-4 shrink-0 rounded-[4px] border border-[var(--border)]/60 object-cover"
              />
            ) : (
              <item.icon
                size={13}
                strokeWidth={1.7}
                className="shrink-0 text-[var(--muted-foreground)]"
              />
            )}
            <span className="shrink-0 font-medium text-[var(--muted-foreground)]">
              {item.kind}
            </span>
            <span className="min-w-0 truncate text-[var(--muted-foreground)]/80">
              {item.label}
            </span>
          </>
        );
        return (
          <span
            key={item.key}
            className={`group/ref flex max-w-full items-center gap-1.5 text-[12px] leading-[1.6] ${rowDirClass}`}
          >
            {item.onClick ? (
              <button
                type="button"
                onClick={item.onClick}
                className={`flex min-w-0 items-center gap-1.5 rounded-md text-left transition-colors hover:text-[var(--foreground)] [&>span]:hover:text-[var(--foreground)] ${rowDirClass}`}
              >
                {Inner}
              </button>
            ) : (
              Inner
            )}
            {item.onRemove ? (
              <button
                type="button"
                onClick={item.onRemove}
                aria-label={t("Remove")}
                className="shrink-0 rounded p-0.5 text-[var(--muted-foreground)]/60 opacity-0 transition-opacity hover:text-[var(--foreground)] focus-visible:opacity-100 group-hover/ref:opacity-100"
              >
                <X size={11} strokeWidth={2} />
              </button>
            ) : null}
          </span>
        );
      })
    : null;

  const summary = collapsible ? (
    <button
      type="button"
      onClick={() => setExpanded((prev) => !prev)}
      aria-expanded={expanded}
      className={`flex items-center gap-1.5 rounded-md text-[12px] font-medium leading-[1.6] text-[var(--muted-foreground)]/80 transition-colors hover:text-[var(--foreground)] ${rowDirClass}`}
    >
      <FoldMark visible={!expanded} />
      <span>
        {items.length} {summaryNoun}
      </span>
      <ChevronDown
        size={11}
        strokeWidth={2}
        className={`shrink-0 transition-transform ${
          // The chevron points where tapping will reveal rows: up-direction
          // trees expand upward, down-direction trees expand downward.
          expanded ? "rotate-180" : direction === "up" ? "" : "-rotate-90"
        }`}
      />
    </button>
  ) : null;

  return (
    <div className={`flex flex-col gap-0.5 ${alignClass}`}>
      {/* "up" reads bottom-to-top: rows stack above the toggle so the
          block grows away from the textarea. "down" is the inverse. */}
      {direction === "up" ? (
        <>
          {rows}
          {summary}
        </>
      ) : (
        <>
          {summary}
          {rows}
        </>
      )}
    </div>
  );
});

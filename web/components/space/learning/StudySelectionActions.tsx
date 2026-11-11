"use client";

/**
 * StudySelectionActions — what a passage selected inside a mastery transcript
 * can become.
 *
 * The main chat page answers a selection with "Add to chat" and a side chat.
 * A study session has neither: the tutor is the only conversation, and the
 * learner usually does not want to write a question from scratch — they want
 * the same explanation again, an example, or the background they are missing.
 * So the actions here are the questions they would otherwise have to phrase:
 * explain, give an example, simplify, admit confusion, or look up a term. Each
 * one sends its own message; "Add to input" is the escape hatch for anything
 * else.
 */

import { useEffect, useState } from "react";
import { HelpCircle, Lightbulb, ListTree, MessageSquarePlus, SpellCheck, Unplug } from "lucide-react";
import { useTranslation } from "react-i18next";

export type StudyAskKind = "explain" | "example" | "simpler" | "lost" | "term";

export interface SelectionAnchor {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

const BAR_WIDTH = 392;
const BAR_HEIGHT = 36;
const EDGE = 12;
const GAP = 8;

/** Below the selection's last line, or above it when the bottom is near. */
function place(anchor: SelectionAnchor) {
  const left = Math.max(
    EDGE,
    Math.min(anchor.right - BAR_WIDTH, window.innerWidth - BAR_WIDTH - EDGE),
  );
  const below = anchor.bottom + GAP;
  const fitsBelow = below + BAR_HEIGHT <= window.innerHeight - EDGE;
  const top = fitsBelow ? below : Math.max(EDGE, anchor.top - BAR_HEIGHT - GAP);
  return { left, top };
}

export default function StudySelectionActions({
  anchor,
  termEligible,
  disabled,
  onAsk,
  onPrefill,
  onDismiss,
}: {
  anchor: SelectionAnchor;
  /** The selection is short enough to be a single term worth defining. */
  termEligible: boolean;
  disabled: boolean;
  onAsk: (kind: StudyAskKind) => void;
  onPrefill: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const { left, top } = place(anchor);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      if (menuOpen) setMenuOpen(false);
      else onDismiss();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [menuOpen, onDismiss]);

  const segment =
    "inline-flex h-full items-center gap-1.5 px-2.5 text-[12.5px] font-medium transition-colors hover:bg-[color-mix(in_srgb,var(--background)_14%,transparent)] focus-visible:outline-none focus-visible:bg-[color-mix(in_srgb,var(--background)_18%,transparent)] disabled:pointer-events-none disabled:opacity-40";

  return (
    <div
      role="toolbar"
      aria-label={t("Ask about this passage")}
      // Keep the selection: a press here must not collapse it before the click.
      onPointerDown={(event) => event.preventDefault()}
      className="fixed z-[45]"
      style={{ left, top, width: BAR_WIDTH }}
    >
      <div
        className="flex items-stretch overflow-hidden rounded-xl bg-[var(--foreground)] text-[var(--background)] shadow-lg"
        style={{ height: BAR_HEIGHT }}
      >
        <button type="button" disabled={disabled} onClick={() => onAsk("explain")} className={segment}>
          <HelpCircle size={14} strokeWidth={1.8} aria-hidden="true" />
          {t("Explain")}
        </button>
        <button type="button" disabled={disabled} onClick={() => onAsk("example")} className={segment}>
          <Lightbulb size={14} strokeWidth={1.8} aria-hidden="true" />
          {t("Example")}
        </button>
        <button type="button" disabled={disabled} onClick={() => onAsk("simpler")} className={segment}>
          <ListTree size={14} strokeWidth={1.8} aria-hidden="true" />
          {t("Simpler")}
        </button>
        <button type="button" disabled={disabled} onClick={() => onAsk("lost")} className={segment}>
          <Unplug size={14} strokeWidth={1.8} aria-hidden="true" />
          {t("I'm lost")}
        </button>
        {termEligible ? (
          <button type="button" disabled={disabled} onClick={() => onAsk("term")} className={segment}>
            <SpellCheck size={14} strokeWidth={1.8} aria-hidden="true" />
            {t("Explain term")}
          </button>
        ) : null}
        <span
          aria-hidden="true"
          className="my-2 w-px bg-[color-mix(in_srgb,var(--background)_22%,transparent)]"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={onPrefill}
          aria-label={t("Add to input")}
          className={`${segment} px-2`}
        >
          <MessageSquarePlus size={14} strokeWidth={1.8} aria-hidden="true" />
          {t("Add to input")}
        </button>
      </div>
    </div>
  );
}

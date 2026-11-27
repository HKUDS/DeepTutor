"use client";

import { useEffect, useRef, useState } from "react";
import { BrainCircuit, ChevronDown, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import MarkdownRenderer from "./MarkdownRenderer";

interface ModelThinkingCardProps {
  /** Inner text of a single <think>...</think> block (already trimmed). */
  content: string;
  /**
   * False while the model is still streaming inside the open <think> tag, so
   * the card stays expanded and shows a spinner. Once the closing tag arrives
   * the card auto-collapses (default-folded) unless the user has pinned it
   * open or closed manually.
   */
  closed: boolean;
}

/**
 * Collapsible card that surfaces a reasoning model's raw <think> scratchpad
 * in a way that visually echoes the system trace panels (subtle border,
 * muted typography) without being mistaken for one.
 *
 * Behaviour:
 *  - Default-open while the model is still writing the scratchpad so the
 *    user can watch reasoning happen live.
 *  - Auto-collapses the moment the closing tag arrives.
 *  - Once the user toggles the card themselves, their preference wins for
 *    the rest of the message lifetime.
 */
export default function ModelThinkingCard({
  content,
  closed,
}: ModelThinkingCardProps) {
  const { t } = useTranslation();
  const [userToggled, setUserToggled] = useState<boolean | null>(null);
  const detailsRef = useRef<HTMLDetailsElement>(null);

  const open = userToggled !== null ? userToggled : !closed;

  // Keep the underlying <details> element in sync with our derived `open`
  // state. We do not bind `open` as a controlled prop because React strips
  // the boolean attribute on `false`, which races with the browser's
  // built-in toggle handling and produces a flicker the first time `closed`
  // flips during streaming.
  useEffect(() => {
    const el = detailsRef.current;
    if (el && el.open !== open) {
      el.open = open;
    }
  }, [open]);

  const handleToggle = (event: React.SyntheticEvent<HTMLDetailsElement>) => {
    const next = event.currentTarget.open;
    if (next !== open) {
      setUserToggled(next);
    }
  };

  const hasBody = content.trim().length > 0;
  const placeholder = `${t("Thinking...")}`;

  return (
    <details
      ref={detailsRef}
      onToggle={handleToggle}
      className="group/think my-3 overflow-hidden rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40 transition-colors hover:border-[var(--border)]"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] [&::-webkit-details-marker]:hidden">
        <ChevronDown
          size={12}
          strokeWidth={1.8}
          className="shrink-0 opacity-70 transition-transform group-open/think:rotate-180"
        />
        <BrainCircuit
          size={12}
          strokeWidth={1.6}
          className="shrink-0 opacity-80"
        />
        <span className="tracking-wide">{t("Model thinking")}</span>
        {!closed && (
          <Loader2
            size={11}
            strokeWidth={1.8}
            className="ms-1 animate-spin text-[var(--muted-foreground)]/70"
          />
        )}
      </summary>
      <div className="border-t border-[var(--border)]/40 bg-[var(--background)]/40 px-3 py-2">
        {hasBody ? (
          <MarkdownRenderer content={content} variant="trace" />
        ) : (
          <div className="text-[11px] italic text-[var(--muted-foreground)]/70">
            {placeholder}
          </div>
        )}
      </div>
    </details>
  );
}

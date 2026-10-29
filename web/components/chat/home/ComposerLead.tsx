"use client";

import { useLayoutEffect, useRef } from "react";
import { X, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";

export interface LeadToken {
  key: string;
  icon: LucideIcon;
  label: string;
  /** What sort of thing it is, for the remove hint: "Skills", "MCP". */
  kind: string;
  onRemove: () => void;
}

/** Past this many, the rest fold into one "+N". */
const SHOWN = 3;

/**
 * What this message uses, written at the start of it.
 *
 * Skills and connectors picked in the tray are not attachments, so they do
 * not sit in the attachment row: they read as the opening words of the
 * message, the way a command does, and the text starts after them. The strip
 * floats over the first line and reports its width; the input indents its
 * first line by that much, so wrapping and the caret behave as if the tokens
 * were really there. Hovering a token turns its icon into a remove mark.
 */
export function ComposerLead({
  tokens,
  armed,
  hidden,
  onWidth,
}: {
  tokens: LeadToken[];
  /** Backspace at the start of the text marked the last token for removal. */
  armed: boolean;
  /** The text has scrolled under the first line; keep out of its way. */
  hidden: boolean;
  onWidth: (width: number) => void;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    // offsetWidth ignores the entry transform, so the indent lands once.
    const report = () => onWidth(node.offsetWidth);
    report();
    const observer = new ResizeObserver(report);
    observer.observe(node);
    return () => {
      observer.disconnect();
      onWidth(0);
    };
  }, [onWidth]);
  const shown = tokens.length > SHOWN ? tokens.slice(0, SHOWN - 1) : tokens;
  const rest = tokens.slice(shown.length);
  return (
    <div
      ref={ref}
      role="group"
      aria-label={t("composer.lead.label")}
      className="dt-composer-lead"
      data-hidden={hidden || undefined}
    >
      {shown.map((token, index) => (
        <Tooltip key={token.key} label={`${t("Remove")} ${token.label}`} description={token.kind} side="top">
          <button
            type="button"
            onClick={token.onRemove}
            aria-label={`${t("Remove")} ${token.kind} · ${token.label}`}
            data-armed={(armed && !rest.length && index === shown.length - 1) || undefined}
            className="dt-lead-token"
          >
            <span aria-hidden className="dt-lead-icon">
              <token.icon size={15} strokeWidth={1.8} />
              <X size={14} strokeWidth={2.2} />
            </span>
            <span className="dt-lead-label">{token.label}</span>
          </button>
        </Tooltip>
      ))}
      {rest.length > 0 && (
        <Tooltip label={rest.map((token) => token.label).join(" · ")} side="top">
          <span tabIndex={0} className="dt-lead-more" data-armed={armed || undefined}>
            +{rest.length}
          </span>
        </Tooltip>
      )}
    </div>
  );
}

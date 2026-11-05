"use client";

import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";

/** The rule-and-words look every quoted passage shares, sent or not. */
export const QUOTE_RULE_CLASS =
  "border-l-2 border-[color-mix(in_srgb,var(--primary)_45%,transparent)] pl-2.5 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]";

/**
 * A passage the next message is about, inside the box it will be sent from.
 *
 * Drawn the way the sent bubble draws it (a rule and the words, no card), so
 * the quote looks the same before and after it goes.
 */
export function QuotedPassage({
  quote,
  onRemove,
}: {
  quote: string;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-1.5 px-4 pt-3">
      <p
        className={`line-clamp-2 min-w-0 flex-1 whitespace-pre-line ${QUOTE_RULE_CLASS}`}
      >
        {quote}
      </p>
      <Tooltip label={t("Remove quoted passage")}>
        <button
          type="button"
          aria-label={t("Remove quoted passage")}
          onClick={onRemove}
          className="-mr-1 inline-flex size-6 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <X size={12} />
        </button>
      </Tooltip>
    </div>
  );
}

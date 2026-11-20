"use client";

import { SquareDashedMousePointer, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/shared/ui/Tooltip";

/**
 * A marked page area the next message is about, inside the composer (#2741).
 *
 * The area itself is cropped server-side from the stored PDF when the message
 * is sent, so the chip only names it; removing it sends a plain question.
 */
export function MarkedRegionChip({
  locator,
  onRemove,
}: {
  locator: number;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-1.5 px-4 pt-3">
      <span
        data-marked-region-chip=""
        className="inline-flex min-w-0 items-center gap-1.5 rounded-md border border-[color-mix(in_srgb,var(--primary)_35%,transparent)] bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] px-2 py-0.5 text-[12px] text-[var(--foreground)]"
      >
        <SquareDashedMousePointer size={12} className="shrink-0 text-[var(--primary)]" />
        <span className="truncate">{t("Area on page {{page}}", { page: locator })}</span>
      </span>
      <Tooltip label={t("Remove marked area")}>
        <button
          type="button"
          aria-label={t("Remove marked area")}
          onClick={onRemove}
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <X size={12} />
        </button>
      </Tooltip>
    </div>
  );
}

"use client";

import { ArrowDown } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * The "back to latest" affordance shown while a reply streams and the reader
 * has scrolled away from the live end. The caller owns visibility so the
 * control only exists when there is new content to return to.
 */
export default function ScrollToLatestButton({
  visible,
  onClick,
  className = "",
}: {
  visible: boolean;
  onClick: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  if (!visible) return null;
  return (
    <button
      type="button"
      aria-label={t("Back to latest")}
      onClick={onClick}
      className={`inline-flex h-8 items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--popover)] px-3 text-[12px] font-medium text-[var(--popover-foreground)] shadow-[0_10px_30px_-12px_var(--overlay)] transition-colors hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${className}`}
    >
      <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
      <span>{t("Back to latest")}</span>
    </button>
  );
}

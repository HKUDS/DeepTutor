"use client";

import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

/** A selected course or resource with a clear action. */
export function RailSlot({
  children,
  onClear,
  clearLabel,
}: {
  children: React.ReactNode;
  onClear?: () => void;
  clearLabel?: string;
}) {
  const { t } = useTranslation();
  const label = clearLabel ?? t("Clear");
  return (
    <div className="group/rail inline-flex min-w-0 max-w-full items-center">
      {children}
      {onClear ? (
        <button
          type="button"
          onClick={onClear}
          aria-label={label}
          title={label}
          className="-ml-1.5 mr-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-60 sm:opacity-0 transition-[opacity,background-color,color] duration-150 hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:opacity-100 group-hover/rail:opacity-100"
        >
          <X size={12} strokeWidth={2.2} />
        </button>
      ) : null}
    </div>
  );
}

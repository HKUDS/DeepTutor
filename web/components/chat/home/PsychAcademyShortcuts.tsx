"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { PSYCH_ACADEMY_SHORTCUTS } from "@/lib/psych-academy-shortcuts";

/**
 * Academy workspace entry points on the Home empty screen — links to dedicated
 * pages (/counsel, /sim, /distill, /train) rather than stuffing psych
 * capabilities into the Home composer.
 */
export default function PsychAcademyShortcuts() {
  const { t } = useTranslation();

  return (
    <div className="mx-auto w-full max-w-[768px] px-6 pb-4 animate-fade-in">
      <p className="mb-2.5 text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {t("Psych Academy")}
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {PSYCH_ACADEMY_SHORTCUTS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              href={item.href}
              title={t(item.tooltipKey)}
              className="group flex flex-col gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--card)]/60 px-3 py-2.5 text-left transition-colors hover:border-[var(--ring)] hover:bg-[var(--card)]"
            >
              <Icon
                className="h-4 w-4 text-[var(--primary)] transition-transform group-hover:scale-105"
                aria-hidden
              />
              <span className="text-sm font-medium text-[var(--foreground)]">
                {t(item.labelKey)}
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

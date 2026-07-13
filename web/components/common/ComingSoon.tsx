"use client";

import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * Full-height "coming soon" placeholder for a shelved feature whose route
 * still exists (so a hand-typed URL lands somewhere graceful) but whose UI
 * is being reworked. ``label`` names the feature; ``description`` overrides
 * the default copy.
 */
export default function ComingSoon({
  label,
  description,
}: {
  label?: string;
  description?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col items-center justify-center gap-4 px-8 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--muted)]/50">
        <Sparkles
          size={24}
          strokeWidth={1.6}
          className="text-[var(--muted-foreground)]"
        />
      </div>
      <div className="flex flex-col items-center gap-2">
        {label ? (
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]/70">
            {label}
          </span>
        ) : null}
        <h1 className="font-serif text-[30px] font-medium leading-[1.1] tracking-[-0.015em] text-[var(--foreground)]">
          {t("Coming soon")}
        </h1>
        <p className="mt-1 max-w-sm text-[13.5px] leading-relaxed text-[var(--muted-foreground)]">
          {description ??
            t("This feature is being reworked and will be back soon.")}
        </p>
      </div>
    </div>
  );
}

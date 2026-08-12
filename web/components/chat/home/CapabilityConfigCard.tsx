"use client";

/**
 * CapabilityConfigCard — section card hosted at the bottom of the chat
 * Activity panel that holds the configuration form for the active
 * capability (Quiz / Animator / Visualize / Research).
 *
 * The body (the actual form) is provided by the parent as children so this
 * card stays agnostic of which fields the capability collects. The card
 * provides the chrome: header (capability icon + label) and a confirm
 * footer that gates message sending.
 *
 * Sending a message is allowed only after the user clicks *Confirm*. Any
 * subsequent field edit invalidates the confirmation upstream (see
 * page.tsx), restoring the Confirm button.
 */

import { memo, type ReactNode } from "react";
import {
  BarChart3,
  Check,
  Clapperboard,
  Microscope,
  PenLine,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

export type ConfigurableCapability =
  | "deep_question"
  | "math_animator"
  | "visualize"
  | "deep_research";

interface CapabilityChrome {
  icon: LucideIcon;
  label: string;
}

const CAPABILITY_CHROME: Record<ConfigurableCapability, CapabilityChrome> = {
  deep_question: { icon: PenLine, label: "Quiz settings" },
  math_animator: { icon: Clapperboard, label: "Animator settings" },
  visualize: { icon: BarChart3, label: "Visualize settings" },
  deep_research: { icon: Microscope, label: "Research settings" },
};

interface CapabilityConfigCardProps {
  capability: ConfigurableCapability;
  confirmed: boolean;
  canConfirm: boolean;
  validationErrors?: string[];
  onConfirm: () => void;
  children: ReactNode;
}

function CapabilityConfigCardInner({
  capability,
  confirmed,
  canConfirm,
  validationErrors,
  onConfirm,
  children,
}: CapabilityConfigCardProps) {
  const { t } = useTranslation();
  const { icon: Icon, label } = CAPABILITY_CHROME[capability];
  const hasErrors = !!validationErrors?.length;

  return (
    <section className="overflow-hidden rounded-xl border border-[var(--border)]/55 bg-[var(--card)] shadow-[0_1px_2px_color-mix(in_srgb,var(--foreground)_5%,transparent),0_4px_14px_color-mix(in_srgb,var(--foreground)_5%,transparent)]">
      <header className="flex items-center gap-2 border-b border-[var(--border)]/35 px-3.5 py-2.5">
        <Icon
          size={13}
          strokeWidth={1.8}
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        <span className="flex-1 text-[12px] font-semibold tracking-[0.005em] text-[var(--foreground)]">
          {t(label)}
        </span>
        {confirmed ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] px-2 py-[2px] text-[10px] font-semibold text-[var(--primary)]">
            <Check size={10} strokeWidth={2.5} />
            {t("Confirmed")}
          </span>
        ) : (
          <span className="shrink-0 rounded-full bg-[var(--muted)]/55 px-1.5 py-[1px] text-[10px] font-semibold text-[var(--muted-foreground)]">
            {t("Required")}
          </span>
        )}
      </header>
      {/* The form body provided by the parent (a bare ConfigPanel). */}
      <div>{children}</div>
      {hasErrors ? (
        <ul className="space-y-0.5 border-t border-[var(--border)]/30 bg-[color-mix(in_srgb,var(--destructive)_8%,transparent)] px-3.5 py-2 text-[11px] text-[var(--destructive)]">
          {validationErrors!.map((err, i) => (
            <li key={i}>• {err}</li>
          ))}
        </ul>
      ) : null}
      <footer className="flex items-center justify-between gap-2 border-t border-[var(--border)]/35 bg-[var(--background)]/40 px-3.5 py-2">
        <span className="min-w-0 flex-1 truncate text-[10.5px] text-[var(--muted-foreground)]/75">
          {confirmed
            ? t("Edit any field to update settings.")
            : t("Confirm settings to enable sending.")}
        </span>
        <button
          type="button"
          onClick={onConfirm}
          disabled={confirmed || !canConfirm}
          className={`shrink-0 rounded-md px-2.5 py-1 text-[11px] font-semibold transition-[background-color,box-shadow,opacity] disabled:cursor-not-allowed ${
            confirmed
              ? "bg-transparent text-[var(--muted-foreground)]/45"
              : "bg-[var(--primary)] text-[var(--primary-foreground)] shadow-[0_2px_6px_color-mix(in_srgb,var(--primary)_28%,transparent)] hover:shadow-[0_4px_10px_color-mix(in_srgb,var(--primary)_40%,transparent)] disabled:bg-[var(--muted-foreground)]/15 disabled:text-[var(--muted-foreground)]/40 disabled:shadow-none"
          }`}
        >
          {confirmed ? t("Confirmed") : t("Confirm")}
        </button>
      </footer>
    </section>
  );
}

const CapabilityConfigCard = memo(CapabilityConfigCardInner);
export default CapabilityConfigCard;

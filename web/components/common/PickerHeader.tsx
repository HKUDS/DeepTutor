"use client";

import { X, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * Shared header for the fullscreen context pickers (History, Books, Memory,
 * My Agents, Persona, Question Bank). Every picker used to hand-roll the same
 * three-line header: an all-caps, wide-tracked "eyebrow" kind label, a title,
 * and a subtitle.
 *
 * That eyebrow is a Latin-typography idiom — `uppercase` + `tracking-[0.14em]`
 * reads as refined on English, but on CJK it just spreads the glyphs apart and
 * looks loose/unkempt (uppercase is a no-op for Han characters). So this
 * component drops the eyebrow entirely and conveys the "kind" through a tinted
 * icon chip instead: cleaner, script-agnostic, and consistent across pickers.
 */
export default function PickerHeader({
  icon: Icon,
  titleId,
  title,
  subtitle,
  onClose,
  trailing,
}: {
  icon: LucideIcon;
  /** id wired to the dialog's `aria-labelledby`. */
  titleId: string;
  /** Already-translated title string. */
  title: string;
  /** Already-translated subtitle string. */
  subtitle: string;
  onClose: () => void;
  /** Optional control rendered between the title block and the close button. */
  trailing?: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-3.5 border-b border-[var(--border)] px-5 py-4">
      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--primary)]/10 text-[var(--primary)]">
        <Icon className="h-[18px] w-[18px]" strokeWidth={1.8} />
      </div>
      <div className="min-w-0 flex-1">
        <h2
          id={titleId}
          className="text-[15px] font-semibold leading-tight text-[var(--foreground)]"
        >
          {title}
        </h2>
        <p className="mt-1 text-[13px] leading-snug text-[var(--muted-foreground)]">
          {subtitle}
        </p>
      </div>
      {trailing}
      <button
        onClick={onClose}
        className="-mr-1 -mt-1 shrink-0 rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        aria-label={t("Close")}
      >
        <X size={18} />
      </button>
    </div>
  );
}

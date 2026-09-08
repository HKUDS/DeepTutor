"use client";

/**
 * Post-payment success overlay.
 *
 * A short, celebratory layer on top of the paid state: a confetti burst
 * (reusing the portalled canvas effect) and a compact grant summary, then a
 * button to close and land on the refreshed shelf. `onDone` fires when the
 * overlay asks to dismiss, not when the confetti finishes, so a reader who
 * lingers keeps the message on screen.
 */

import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Sparkles } from "lucide-react";
import { Button } from "@/shared/ui/Button";
import { LevelUpCelebration } from "@/components/space/learning/LevelUpCelebration";

export interface PaymentSuccessOverlayProps {
  /** Human plan label that was just unlocked. */
  planName: string;
  /** Human channel label shown under the headline (e.g. "WeChat Pay"). */
  channelLabel?: string;
  /** Extra line rendered under the summary (e.g. what was refreshed). */
  detail?: string;
  onDismiss: () => void;
  /** Confetti even when the learner prefers reduced motion is skipped. */
  celebrate?: boolean;
}

export function PaymentSuccessOverlay({
  planName,
  channelLabel,
  detail,
  onDismiss,
  celebrate = true,
}: PaymentSuccessOverlayProps) {
  const { t } = useTranslation();

  const close = useCallback(() => onDismiss(), [onDismiss]);

  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      {celebrate ? (
        <LevelUpCelebration key={planName} onDone={() => undefined} />
      ) : null}

      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[var(--success)]/15">
        <CheckCircle2 className="h-8 w-8 text-[var(--success)]" aria-hidden />
      </div>

      <div>
        <p className="text-base font-semibold text-[var(--foreground)]">
          {t("You’re all set!")}
        </p>
        <p className="mt-1 max-w-[280px] text-[12px] leading-5 text-[var(--muted-foreground)]">
          {t("“{{plan}}” is now active on your account.", {
            plan: planName,
          })}
          {channelLabel ? ` ${t("Paid via {{channel}}", { channel: channelLabel })}` : ""}
        </p>
        {detail ? (
          <p className="mt-1 flex items-center justify-center gap-1 text-[11px] text-[var(--muted-foreground)]/80">
            <Sparkles className="h-3 w-3" aria-hidden />
            {detail}
          </p>
        ) : null}
      </div>

      <Button size="sm" className="mt-1" onClick={close}>
        {t("Done")}
      </Button>
    </div>
  );
}
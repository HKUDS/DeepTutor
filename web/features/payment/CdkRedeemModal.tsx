"use client";

/**
 * Card-key (CDK) redemption modal.
 *
 * Accepts a code pasted or typed by a learner, calls the redemption endpoint,
 * and reports the granted plan. On success the parent refreshes entitlements
 * so the new books/question banks appear immediately.
 */

import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Ticket } from "lucide-react";
import { Dialog } from "@/shared/ui/Dialog";
import { Button } from "@/shared/ui/Button";
import { InlineAlert } from "@/shared/ui/InlineAlert";
import { redeemCdk, type CdkRedeemResponse } from "@/lib/payment-api";

export interface CdkRedeemModalProps {
  open: boolean;
  onClose: () => void;
  /** Called once a code was redeemed so the shelf/permissions can refresh. */
  onRedeemed: (result: CdkRedeemResponse) => void;
}

export function CdkRedeemModal({ open, onClose, onRedeemed }: CdkRedeemModalProps) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<CdkRedeemResponse | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const normalized = code.trim().toUpperCase();
  const canSubmit = normalized.length >= 8;

  const submit = useCallback(async () => {
    if (!canSubmit || busy) return;
    setBusy(true);
    setError("");
    setDone(null);
    try {
      const result = await redeemCdk(normalized);
      setDone(result);
      onRedeemed(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [canSubmit, busy, normalized, onRedeemed]);

  // The backend returns the granted plan inside `plan`; surface its name and
  // duration the same way the online purchase flow does.
  const planName = done?.plan?.name ?? done?.grant?.plan_name;
  const durationDays =
    typeof done?.plan?.duration_days === "number" ? done.plan.duration_days : undefined;

  const close = useCallback(() => {
    if (busy) return;
    onClose();
    // Reset on next open rather than on close so the carrier state (error or
    // success) stays visible while the dialog closes.
    requestAnimationFrame(() => {
      setCode("");
      setError("");
      setDone(null);
    });
  }, [busy, onClose]);

  return (
    <Dialog
      open={open}
      onClose={close}
      busy={busy}
      title={t("Redeem a card key")}
      description={t(
        "Enter a card-key code to unlock books, question banks and model access.",
      )}
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={close}>
            {t("Cancel")}
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={!canSubmit || busy}
            loading={busy}
          >
            {t("Redeem")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Card key code")}
          </span>
          <div className="relative">
            <Ticket
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]/60"
            />
            <input
              ref={inputRef}
              data-autofocus
              value={code}
              onChange={(e) => {
                setCode(e.target.value.toUpperCase());
                if (error) setError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submit();
              }}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              autoComplete="off"
              spellCheck={false}
              className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--secondary)]/40 pl-9 pr-3 font-mono text-sm tracking-widest text-[var(--foreground)] placeholder:text-[var(--muted-foreground)]/50 focus:border-[var(--primary)]/50 focus:outline-none"
            />
          </div>
          <span className="mt-1 block text-[10px] text-[var(--muted-foreground)]/70">
            {t("Codes are case-insensitive — you can paste the whole string.")}
          </span>
        </label>

        {error ? (
          <InlineAlert tone="danger" title={t("Could not redeem")}>
            {error}
          </InlineAlert>
        ) : null}

        {done ? (
          <InlineAlert tone="success" title={t("Success — unlocked!")}>
            {planName
              ? t("“{{plan}}” is now active on your account.", { plan: planName })
              : t("The plan is now active on your account.")}
            {durationDays && durationDays > 0
              ? t(" ({{days}} days)", { days: durationDays })
              : ""}
          </InlineAlert>
        ) : null}

        {busy ? (
          <div className="flex items-center justify-center gap-2 py-1 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            {t("Redeeming…")}
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
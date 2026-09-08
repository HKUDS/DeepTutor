"use client";

/**
 * Student purchase + CDK redemption entry point.
 *
 * A compact "Upgrade" affordance for the learner-facing surface (mounted in
 * the book library header). Opening it shows the plan catalogue; a second
 * action opens the card-key redemption dialog. After any grant lands it calls
 * `onEntitlementChanged` so the mounted screen re-pulls its books/shelf.
 *
 * Everything is gated on the catalogue actually loading — on a deployment
 * with no plans published the entry simply does not render, so a vanilla
 * DeepTutor install is visually unchanged.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreditCard, Loader2, Ticket } from "lucide-react";
import { notify } from "@/lib/notifications";
import { fetchPaymentPlans, type PaymentPlan } from "@/lib/payment-api";
import { CdkRedeemModal } from "./CdkRedeemModal";
import { PurchaseModal } from "./PurchaseModal";

export interface PurchaseEntryProps {
  /** Re-pull books / shelf after a grant so new content appears immediately. */
  onEntitlementChanged: () => void;
}

export function PurchaseEntry({ onEntitlementChanged }: PurchaseEntryProps) {
  const { t } = useTranslation();
  const [purchaseOpen, setPurchaseOpen] = useState(false);
  const [cdkOpen, setCdkOpen] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);

  // Probe once: only show the affordance when the payment catalogue exists.
  useEffect(() => {
    let alive = true;
    fetchPaymentPlans()
      .then((data) => {
        if (!alive) return;
        setEnabled((data.plans?.length ?? 0) > 0 || data.cdk_enabled === true);
      })
      .catch(() => {
        if (alive) setEnabled(false);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const handleEntitlementChanged = useCallback(() => {
    notify(t("Your access has been updated."), { tone: "success" });
    onEntitlementChanged();
  }, [onEntitlementChanged, t]);

  if (loading) return null;
  if (!enabled) return null;

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => setCdkOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)]"
      >
        <Ticket size={13} aria-hidden />
        {t("Redeem code")}
      </button>
      <button
        type="button"
        onClick={() => setPurchaseOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
      >
        <CreditCard size={13} aria-hidden />
        {t("Upgrade")}
      </button>

      <PurchaseModal
        open={purchaseOpen}
        onClose={() => setPurchaseOpen(false)}
        onEntitlementChanged={handleEntitlementChanged}
      />
      <CdkRedeemModal
        open={cdkOpen}
        onClose={() => setCdkOpen(false)}
        onRedeemed={() => handleEntitlementChanged()}
      />
    </div>
  );
}
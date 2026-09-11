"use client";

/**
 * Purchase modal — the single surface a learner pays from.
 *
 * Owns the three-step flow the issue describes:
 *
 *   1. plan picked on the cards  →  quoted here
 *   2. gateway chosen → order created → QR shown, status polled
 *   3. payment confirmed → success overlay → shelf/permissions refreshed
 *
 * On success it invalidates the cached auth/capability state and calls
 * `onEntitlementChanged`, which the mounting screen uses to re-pull its
 * library and knowledge list so the newly granted books appear immediately.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, ShieldCheck, WalletCards } from "lucide-react";
import { Dialog } from "@/shared/ui/Dialog";
import { Button } from "@/shared/ui/Button";
import { InlineAlert } from "@/shared/ui/InlineAlert";
import {
  createPaymentOrder,
  fetchPaymentPlans,
  type PaymentOrder,
  type PaymentPlan,
} from "@/lib/payment-api";
import { invalidateAuthStatusCache } from "@/lib/auth";
import { PaymentQrPane } from "./PaymentQrModal";
import { PaymentSuccessOverlay } from "./PaymentSuccessOverlay";
import { PricingSection } from "./PricingSection";

type PurchaseStep = "plans" | "gateway" | "qr" | "success";

const CHANNEL_LABELS: Record<string, string> = {
  wechat: "WeChat Pay",
  epay: "EPay",
};

function channelLabel(gateway: string): string {
  return CHANNEL_LABELS[gateway] ?? gateway;
}

export interface PurchaseModalProps {
  open: boolean;
  onClose: () => void;
  /** Mounted screen re-pulls its data (shelf, knowledge list) after a grant. */
  onEntitlementChanged: () => void;
}

export function PurchaseModal({
  open,
  onClose,
  onEntitlementChanged,
}: PurchaseModalProps) {
  const { t } = useTranslation();
  const [step, setStep] = useState<PurchaseStep>("plans");
  const [plans, setPlans] = useState<PaymentPlan[]>([]);
  const [gateways, setGateways] = useState<string[]>([]);
  const [loadingPlans, setLoadingPlans] = useState(false);
  const [plansError, setPlansError] = useState("");
  const [selectedPlan, setSelectedPlan] = useState<PaymentPlan | null>(null);
  const [busyPlanId, setBusyPlanId] = useState<string | null>(null);
  const [order, setOrder] = useState<PaymentOrder | null>(null);
  const [orderError, setOrderError] = useState("");
  const [creatingOrder, setCreatingOrder] = useState(false);
  const paidRef = useRef(false);

  // Load the catalogue each time the modal opens so a newly published plan or
  // toggled gateway shows up without a page reload.
  useEffect(() => {
    if (!open) return;
    setPlansError("");
    setLoadingPlans(true);
    setStep("plans");
    setSelectedPlan(null);
    setOrder(null);
    setOrderError("");
    paidRef.current = false;
    fetchPaymentPlans()
      .then((data) => {
        setPlans(data.plans ?? []);
        setGateways(data.gateways ?? []);
      })
      .catch((e) => setPlansError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoadingPlans(false));
  }, [open]);

  const resetModal = useCallback(() => {
    setStep("plans");
    setSelectedPlan(null);
    setOrder(null);
    setOrderError("");
    paidRef.current = false;
  }, []);

  const close = useCallback(() => {
    if (creatingOrder) return;
    // If a payment is mid-flight, close anyway — polling dies with the unmount
    // and the user can create a fresh order on reopen.
    onClose();
    requestAnimationFrame(resetModal);
  }, [creatingOrder, onClose, resetModal]);

  const pickGateway = useCallback(
    async (gateway: string) => {
      if (!selectedPlan) return;
      setCreatingOrder(true);
      setOrderError("");
      try {
        const created = await createPaymentOrder({
          plan_id: selectedPlan.id,
          gateway: gateway as "wechat" | "epay",
        });
        setOrder(created);
        setStep("qr");
      } catch (e) {
        setOrderError(e instanceof Error ? e.message : String(e));
      } finally {
        setCreatingOrder(false);
      }
    },
    [selectedPlan],
  );

  /** Terminal grant signal: refresh entitlement state and celebrate. */
  const handlePaid = useCallback(() => {
    if (paidRef.current) return;
    paidRef.current = true;
    try {
      invalidateAuthStatusCache();
    } catch {
      /* no-op — next auth read re-fetches anyway */
    }
    try {
      onEntitlementChanged();
    } catch {
      /* the shelf refresh is best-effort; the grant itself is server-side */
    }
    setStep("success");
  }, [onEntitlementChanged]);

  const retryOrder = useCallback(() => {
    setOrder(null);
    setStep("gateway");
    setOrderError("");
  }, []);

  const gatewaysToShow =
    gateways.length > 0
      ? gateways
      : selectedPlan
        ? ["wechat", "epay"]
        : [];

  return (
    <Dialog
      open={open}
      onClose={close}
      busy={creatingOrder}
      size="lg"
      title={step === "success" ? t("Payment received") : t("Upgrade your study plan")}
      description={
        step === "success"
          ? undefined
          : t("Unlock books, question banks and model access.")
      }
      footer={null}
    >
      {step === "plans" ? (
        <div className="space-y-4">
          {loadingPlans ? (
            <div className="flex items-center justify-center gap-2 py-12 text-[12px] text-[var(--muted-foreground)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t("Loading plans…")}
            </div>
          ) : plansError ? (
            <InlineAlert tone="danger" title={t("Could not load plans")}>
              {plansError}
            </InlineAlert>
          ) : (
            <PricingSection
              plans={plans}
              busyPlanId={busyPlanId}
              onPurchase={async (plan) => {
                setBusyPlanId(plan.id);
                setSelectedPlan(plan);
                try {
                  const data = await fetchPaymentPlans();
                  setGateways(data.gateways ?? []);
                  setStep("gateway");
                } catch {
                  setStep("gateway");
                } finally {
                  setBusyPlanId(null);
                }
              }}
            />
          )}
        </div>
      ) : null}

      {step === "gateway" ? (
        <div className="space-y-3">
          <p className="text-[12px] leading-5 text-[var(--muted-foreground)]">
            {t("How would you like to pay for “{{plan}}”?", {
              plan: selectedPlan?.name ?? "",
            })}
          </p>
          {gatewaysToShow.length === 0 ? (
            <p className="text-[11px] text-[var(--muted-foreground)]">
              {t("No payment channel is enabled. Ask your administrator.")}
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {gatewaysToShow.map((g) => (
                <Button
                  key={g}
                  variant="secondary"
                  className="justify-start"
                  disabled={creatingOrder}
                  loading={creatingOrder && order === null}
                  onClick={() => void pickGateway(g)}
                >
                  <WalletCards className="h-4 w-4" aria-hidden />
                  {t("Pay with {{channel}}", { channel: channelLabel(g) })}
                </Button>
              ))}
            </div>
          )}

          {orderError ? (
            <InlineAlert tone="danger" title={t("Could not create the order")}>
              {orderError}
            </InlineAlert>
          ) : null}

          <p className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]/80">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            {t("Payment is handled securely; your access unlocks automatically.")}
          </p>
        </div>
      ) : null}

      {step === "qr" && order ? (
        <PaymentQrPane
          order={order}
          channelLabel={channelLabel(order.gateway)}
          onPaid={handlePaid}
          onClose={close}
          onRetry={retryOrder}
        />
      ) : null}

      {step === "success" ? (
        <PaymentSuccessOverlay
          planName={selectedPlan?.name ?? t("Your plan")}
          channelLabel={order?.gateway ? channelLabel(order.gateway) : undefined}
          detail={t("Your library and question banks have been refreshed.")}
          onDismiss={close}
        />
      ) : null}
    </Dialog>
  );
}
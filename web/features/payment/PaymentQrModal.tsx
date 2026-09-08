"use client";

/**
 * Scan-to-pay modal for WeChat / Alipay.
 *
 * Creating an order returns either a server-rendered QR SVG (scan-code
 * gateways) or a redirect URL (H5/jump gateways). While the code is on
 * screen this modal polls `GET /api/payment/orders/{id}/status` and, the
 * moment the backend reports `paid`/`granted`, fires `onPaid` so the parent
 * can play the success animation and refresh the learner's entitlements.
 *
 * Polling stops at every terminal state — paid, granted, expired, refunded or
 * failed — and on unmount, so a stale timer can never call `onPaid` after the
 * modal is gone.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  QrCode,
  RefreshCw,
  Timer,
  WalletCards,
} from "lucide-react";
import {
  fetchPaymentOrderStatus,
  type PaymentOrder,
  type PaymentOrderStatus,
} from "@/lib/payment-api";

export const PAYMENT_POLL_INTERVAL_MS = 2000;
/** Give up polling after this long and let the user retry. */
export const PAYMENT_POLL_TIMEOUT_MS = 15 * 60 * 1000;

const TERMINAL: ReadonlySet<PaymentOrderStatus> = new Set([
  "paid",
  "granted",
  "completed",
  "expired",
  "refunded",
  "failed",
]);

function isTerminal(status: PaymentOrderStatus): boolean {
  return TERMINAL.has(status);
}

export interface PaymentQrModalProps {
  order: PaymentOrder;
  /** Human label of the channel shown on the code card. */
  channelLabel: string;
  /** Called exactly once when the backend confirms the order was paid. */
  onPaid: (order: PaymentOrder) => void;
  /** Called when the learner closes the modal or the order expires. */
  onClose: () => void;
  onRetry?: () => void;
  busy?: boolean;
}

export function PaymentQrModal({
  order,
  channelLabel,
  onPaid,
  onClose,
  onRetry,
  busy = false,
}: PaymentQrModalProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<PaymentOrderStatus>(order.status);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const paidRef = useRef(false);

  const paid = status === "paid" || status === "granted" || status === "completed";
  const expired = status === "expired";
  const failed = status === "failed" || status === "refunded";
  /** Ceiling reached — the code has sat too long; treat as expired. */
  const timedOut = elapsed * 1000 >= PAYMENT_POLL_TIMEOUT_MS;
  /** EPay returns a redirect URL instead of a QR — show a jump button. */
  const redirectFlow = !order.qr_svg && !!order.pay_url;

  // Poll until a terminal state. Uses an effect keyed on `status` so each
  // poll result replaces the timer rather than stacking.
  useEffect(() => {
    if (isTerminal(status) || paidRef.current || timedOut) return undefined;
    let cancelled = false;

    const timer = setTimeout(async () => {
      try {
        const next = await fetchPaymentOrderStatus(order.order_id);
        if (cancelled) return;
        setStatus(next.status);
        if (next.granted && !paidRef.current) {
          paidRef.current = true;
          onPaid(order);
        } else if (isTerminal(next.status) && !paidRef.current) {
          paidRef.current = true;
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }, PAYMENT_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [status, order, onPaid, timedOut]);

  // Surface how long the code has been waiting.
  useEffect(() => {
    if (isTerminal(status) || timedOut) return undefined;
    const interval = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(interval);
  }, [status, timedOut]);

  const canRetry = expired || failed || error || timedOut;

  return (
    <div className="flex flex-col items-center gap-4 py-1">
      <div className="relative">
        {order.qr_svg ? (
          <div
            className="h-48 w-48 rounded-xl border border-[var(--border)] bg-white p-2.5 [&_svg]:h-full [&_svg]:w-full"
            // Server-rendered from the payment payload — a QR path, no scripting.
            dangerouslySetInnerHTML={{ __html: order.qr_svg }}
            role="img"
            aria-label={t("Payment QR code")}
          />
        ) : redirectFlow ? (
          <div className="flex h-48 w-48 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--secondary)]/40">
            <WalletCards className="h-10 w-10 text-[var(--primary)]" aria-hidden />
          </div>
        ) : (
          <div className="flex h-48 w-48 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--secondary)]/40">
            <QrCode className="h-8 w-8 text-[var(--muted-foreground)]" aria-hidden />
          </div>
        )}

        {paid ? (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-[var(--card)]/85 backdrop-blur-[1px]">
            <CheckCircle2 className="h-12 w-12 text-[var(--success)]" aria-hidden />
          </div>
        ) : null}

        {busy ? (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-[var(--card)]/70">
            <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" aria-hidden />
          </div>
        ) : null}
      </div>

      <div className="text-center">
        <p className="text-sm font-medium text-[var(--foreground)]">
          {paid
            ? t("Payment received!")
            : redirectFlow
              ? t("Finish with {{channel}}", { channel: channelLabel })
              : t("Scan with {{channel}} to pay", { channel: channelLabel })}
        </p>
        <p className="mt-1 max-w-[260px] text-[11px] leading-5 text-[var(--muted-foreground)]">
          {paid
            ? t("Your books and question banks are being unlocked…")
            : expired || timedOut
              ? t("This code has expired. Start a new payment to continue.")
              : failed
                ? t("This payment did not go through. Please try again.")
                : redirectFlow
                  ? t(
                      "You will be taken to the payment page. This window waits for the result.",
                    )
                  : t(
                      "After you pay, this page updates automatically. Do not close it.",
                    )}
        </p>
      </div>

      {redirectFlow && order.pay_url && !paid ? (
        <a
          href={order.pay_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-xs font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
        >
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          {t("Go to pay")}
        </a>
      ) : null}

      {error ? (
        <p className="max-w-[280px] text-center text-[11px] leading-5 text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {canRetry && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[11px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--ring)]"
        >
          <RefreshCw className="h-3 w-3" aria-hidden />
          {t("Start a new code")}
        </button>
      ) : null}

      {!isTerminal(status) && !error && !timedOut ? (
        <p className="flex items-center gap-1 text-[10px] text-[var(--muted-foreground)]/70">
          <Timer className="h-3 w-3" aria-hidden />
          {t("Waiting for payment…")}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Convenience wrapper used by the purchase modal: renders the QR panel and
 * forwards the paid signal to the parent's success flow.
 */
export function PaymentQrPane(props: PaymentQrModalProps) {
  return <PaymentQrModal {...props} />;
}

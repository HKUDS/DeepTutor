"use client";

/**
 * High-conversion pricing cards for the student purchase surface.
 *
 * Reads the published plan catalogue and lets the learner pick one to pay.
 * Displays a strong default (the admin-recommended plan), densifies the price,
 * and shows each plan's entitlement bullets so the upgrade reason is visible
 * before any clicking happens.
 *
 * Kept presentational: selecting a plan only calls `onPurchase(plan)` — the
 * parent owns the payment modal and the post-payment refresh.
 */

import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/shared/ui/styles";
import { Button } from "@/shared/ui/Button";
import type { PaymentPlan } from "@/lib/payment-api";

interface PricingCardProps {
  plan: PaymentPlan;
  /** The card the constructor tab already highlighted. */
  highlighted?: boolean;
  /** Price formatter override (defaults to ¥ + fen). */
  formatPrice?: (priceFen: number, plan: PaymentPlan) => string;
  onPurchase: (plan: PaymentPlan) => void;
  /** True while an order for this plan is being created. */
  busy?: boolean;
}

function defaultFormatPrice(priceFen: number): string {
  const yuan = priceFen / 100;
  const fixed = Number.isInteger(yuan) ? yuan.toString() : yuan.toFixed(2);
  return `¥${fixed}`;
}

/** "x" suffix for a period, kept short so a 3-card row stays balanced. */
function perDayPrice(priceFen: number, durationDays: number): string {
  if (durationDays <= 0) return "";
  const perDay = priceFen / 100 / durationDays;
  return perDay.toFixed(2);
}

function PricingCard({
  plan,
  highlighted = false,
  formatPrice = defaultFormatPrice,
  onPurchase,
  busy = false,
}: PricingCardProps) {
  const { t } = useTranslation();
  const periodLabel: Record<PaymentPlan["period"], string> = {
    monthly: t("month"),
    quarterly: t("quarter"),
    yearly: t("year"),
  };
  const subtitle = periodLabel[plan.period] ?? plan.period;

  return (
    <div
      className={cn(
        "relative flex min-h-[236px] flex-col rounded-2xl border bg-[var(--card)] p-5 transition-all",
        highlighted
          ? "border-[var(--primary)] shadow-[0_0_0_1px_var(--primary)]"
          : "border-[var(--border)]",
      )}
    >
      {plan.tag ? (
        <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-[var(--primary)] px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--primary-foreground)]">
          {plan.tag}
        </span>
      ) : null}

      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-[var(--foreground)]">
          {plan.name}
        </h3>
        <span className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
          {subtitle}
        </span>
      </div>

      <div className="mt-3 flex items-baseline gap-1">
        <span className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
          {formatPrice(plan.price_fen, plan)}
        </span>
        {plan.duration_days && plan.duration_days > 0 ? (
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {t("per {{days}} days", { days: plan.duration_days })}
          </span>
        ) : (
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {t("lifetime")}
          </span>
        )}
      </div>

      {plan.duration_days && plan.duration_days > 0 ? (
        <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]/80">
          {t("≈ ¥{{price}}/day", {
            price: perDayPrice(plan.price_fen, plan.duration_days),
          })}
        </p>
      ) : null}

      <ul className="mt-4 flex-1 space-y-1.5">
        {(plan.perks ?? []).slice(0, 4).map((perk) => (
          <li
            key={perk}
            className="flex items-start gap-1.5 text-[12px] leading-5 text-[var(--foreground)]/85"
          >
            <Check
              aria-hidden
              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--primary)]"
            />
            <span>{perk}</span>
          </li>
        ))}
      </ul>

      <Button
        variant={highlighted ? "primary" : "secondary"}
        size="sm"
        className="mt-4 w-full"
        onClick={() => onPurchase(plan)}
        loading={busy}
      >
        {t("Buy")}
      </Button>
    </div>
  );
}

export interface PricingSectionProps {
  plans: PaymentPlan[];
  busyPlanId?: string | null;
  formatPrice?: (priceFen: number, plan: PaymentPlan) => string;
  onPurchase: (plan: PaymentPlan) => void;
  /** Rendered under the cards (gateway hints, terms line, etc.). */
  footnote?: React.ReactNode;
}

/**
 * The full pricing row. Highlights a single recommended plan when the
 * catalogue marks one; otherwise leaves all cards equal so the constructor
 * does not invent a default the admin never set.
 */
export function PricingSection({
  plans,
  busyPlanId = null,
  formatPrice,
  onPurchase,
  footnote,
}: PricingSectionProps) {
  const { t } = useTranslation();

  if (plans.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-[var(--border)] px-4 py-6 text-center text-[12px] text-[var(--muted-foreground)]">
        {t("No plans are published yet. Ask your administrator to enable one.")}
      </p>
    );
  }

  const recommendedId =
    plans.find((p) => p.recommended)?.id ?? plans.find((p) => p.tag)?.id ?? null;

  return (
    <div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {plans.map((plan) => (
          <PricingCard
            key={plan.id}
            plan={plan}
            highlighted={plan.id === recommendedId}
            formatPrice={formatPrice}
            onPurchase={onPurchase}
            busy={busyPlanId === plan.id}
          />
        ))}
      </div>
      {footnote ? (
        <p className="mt-3 text-center text-[11px] text-[var(--muted-foreground)]/80">
          {footnote}
        </p>
      ) : null}
    </div>
  );
}
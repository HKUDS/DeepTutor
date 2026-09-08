import { apiFetch, apiUrl } from "@/lib/api";

/**
 * Student-facing payment API client.
 *
 * Backed by the commercial payment engine (`/api/payment/*`) built by the
 * DeepTutor Enterprise payment tasks (RIC-546/547/548). The frontend only
 * reads published plans, creates orders, polls order status and redeems CDK
 * codes — signature verification, order fulfilment and grant provisioning all
 * happen server-side.
 */

/** A purchasable plan as published by the admin console. */
export interface PaymentPlan {
  id: string;
  name: string;
  /** Billing cadence bucket, for local card grouping/highlighting. */
  period: "monthly" | "quarterly" | "yearly";
  /** Price in fen (1 元 = 100 分), the unit the backend stores. */
  price_fen: number;
  /** Human price string as served by the backend (e.g. "¥29.90"). */
  price_display?: string;
  /** Validity, normalised to days. 0 / null means lifetime. */
  duration_days?: number;
  /** Concise per-plan feature bullets (free text, already localised server-side). */
  perks?: string[];
  /** Badge shown next to the plan name (e.g. "Most popular"). */
  tag?: string;
  /** Present when the admin highlighted this plan in the console. */
  recommended?: boolean;
}

/** Public plan catalogue, with active gateways the student may pay via. */
export interface PaymentPlansResponse {
  plans: PaymentPlan[];
  /** Active payment channels, e.g. ["wechat", "alipay"]. */
  gateways?: string[];
  /** True when CDK redemption is enabled on this deployment. */
  cdk_enabled?: boolean;
  /** Optional deployment branding shown on the purchase surface. */
  currency?: string;
}

/** A newly created order; `qr_svg` is a server-rendered QR path when the
 *  chosen gateway pays by scan-code (WeChat native). EPay returns a redirect
 *  URL via `pay_url` instead. */
export interface PaymentOrder {
  order_id: string;
  order_no?: string;
  amount_fen: number;
  currency?: string;
  gateway: string;
  status: PaymentOrderStatus;
  plan_id?: string;
  plan_name?: string;
  qr_svg?: string;
  /** H5/jump gateways return a redirect URL instead of a QR code. */
  pay_url?: string;
  expires_at?: string;
  created_at?: string;
}

export type PaymentOrderStatus =
  | "pending"
  | "paid"
  | "granted"
  | "completed"
  | "refunded"
  | "expired"
  | "failed";

export interface PaymentOrderStatusResponse {
  order_id: string;
  status: PaymentOrderStatus;
  /** When true the payment was received AND entitlements were provisioned. */
  granted?: boolean;
  /** Present on terminal failure. */
  message?: string;
}

/** Result of redeeming a card-key code (mirrors the backend RedeemResponse). */
export interface CdkRedeemResponse {
  code_digest: string;
  redeemed_at?: string | null;
  /** True when the code had already been redeemed (idempotent success). */
  idempotent?: boolean;
  /** The plan the code granted, when redemption succeeded. */
  plan?: {
    id?: string;
    name?: string;
    period?: string;
    duration_days?: number;
    [key: string]: unknown;
  };
  grant?: Record<string, unknown>;
}

/** Error detail shape the CDK endpoints return for failures. */
export interface ApiErrorDetail {
  code?: string;
  message?: string;
}

export async function fetchPaymentPlans(): Promise<PaymentPlansResponse> {
  const res = await apiFetch(apiUrl("/api/payment/plans"));
  if (!res.ok) throw new Error(`Failed to load plans: ${res.status}`);
  return (await res.json()) as PaymentPlansResponse;
}

export interface CreateOrderPayload {
  plan_id: string;
  /** WeChat native pays by QR; EPay redirects to a cashier URL. */
  gateway: "wechat" | "epay";
}

export async function createPaymentOrder(
  payload: CreateOrderPayload,
): Promise<PaymentOrder> {
  const res = await apiFetch(apiUrl("/api/payment/orders/create"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = `Failed to create order: ${res.status}`;
    try {
      const data = (await res.json()) as { message?: string; detail?: string };
      detail = data.message || data.detail || detail;
    } catch {
      /* keep the status-based message */
    }
    throw new Error(detail);
  }
  return (await res.json()) as PaymentOrder;
}

export async function fetchPaymentOrderStatus(
  orderId: string,
): Promise<PaymentOrderStatusResponse> {
  const res = await apiFetch(
    apiUrl(`/api/payment/orders/${encodeURIComponent(orderId)}/status`),
  );
  if (!res.ok) throw new Error(`Failed to fetch order status: ${res.status}`);
  return (await res.json()) as PaymentOrderStatusResponse;
}

export async function redeemCdk(code: string): Promise<CdkRedeemResponse> {
  const res = await apiFetch(apiUrl("/api/payment/cdk/redeem"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: code.trim().toUpperCase() }),
  });
  const data = (await res.json().catch(() => ({}))) as CdkRedeemResponse & {
    detail?: ApiErrorDetail | string;
  };
  if (!res.ok) {
    let message = `Redemption failed: ${res.status}`;
    const detail = data.detail;
    if (detail && typeof detail === "object") {
      message = (detail as ApiErrorDetail).message ?? message;
    } else if (typeof detail === "string") {
      message = detail;
    }
    throw new Error(message);
  }
  return data;
}

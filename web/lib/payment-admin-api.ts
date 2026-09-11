import { apiFetch, apiUrl } from "@/lib/api";

/**
 * Admin commerce-management API client (RIC-550).
 *
 * Backed by the RIC-546 admin surface (`/api/payment/admin/*` for gateway
 * config, plans and the order ledger) plus the CDK router
 * (`/api/payment/cdk/*`).  Every endpoint requires an admin session — the
 * backend enforces it with `require_admin`; this module mirrors their exact
 * request/response shapes so the admin console stays a thin reader/writer.
 */

// ---------------------------------------------------------------------------
// Gateway configuration
// ---------------------------------------------------------------------------

/** One payment channel's stored config; credential keys arrive redacted. */
export interface GatewayChannelConfig {
  enabled?: boolean;
  [key: string]: unknown;
}

export interface GatewayConfigPayload {
  wechat: GatewayChannelConfig;
  epay: GatewayChannelConfig;
  cdk: GatewayChannelConfig;
}

export async function fetchGatewayConfig(): Promise<GatewayConfigPayload> {
  const res = await apiFetch(apiUrl("/api/payment/admin/gateways"));
  if (!res.ok) throw new Error(`Failed to load gateway configuration: ${res.status}`);
  const data = (await res.json()) as { gateways: GatewayConfigPayload };
  return data.gateways ?? { wechat: {}, epay: {}, cdk: {} };
}

export async function saveGatewayConfig(
  payload: GatewayConfigPayload,
): Promise<GatewayConfigPayload> {
  const res = await apiFetch(apiUrl("/api/payment/admin/gateways"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(
      typeof data.detail === "string" ? data.detail : `Failed to save gateway configuration: ${res.status}`,
    );
  }
  const data = (await res.json()) as { gateways: GatewayConfigPayload };
  return data.gateways ?? payload;
}

// ---------------------------------------------------------------------------
// Pricing plans
// ---------------------------------------------------------------------------

export interface AdminPlanKnowledgeBase {
  name: string;
  resource_id?: string;
}

export interface AdminPlanModelEntry {
  profile_id: string;
  model_ids: string[];
}

export interface AdminPlan {
  id: string;
  name: string;
  /** Price in fen (1 元 = 100 分), the backend storage unit. */
  price_fen: number;
  /** Billing cadence bucket: monthly | quarterly | yearly | lifetime. */
  period: string;
  /** Validity in days; null / omitted means lifetime. */
  duration_days?: number | null;
  /** Bound book ids. */
  books: string[];
  /** Bound knowledge-base references `[{"name": "admin:kb:..."}]`. */
  knowledge_bases: AdminPlanKnowledgeBase[];
  /** Bound tool/skill names. */
  skills: string[];
  /** LLM model whitelist `{"llm": [{"profile_id", "model_ids"}]}`. */
  models: { llm: AdminPlanModelEntry[] };
  /** Concise feature bullets shown in the storefront. */
  perks: string[];
  /** Badge shown next to the plan name. */
  tag?: string | null;
  recommended: boolean;
  published: boolean;
}

export interface PlanListResponse {
  plans: AdminPlan[];
}

export interface PlanDetailResponse {
  plan: AdminPlan;
}

const EMPTY_PLAN: AdminPlan = {
  id: "",
  name: "",
  price_fen: 0,
  period: "monthly",
  duration_days: null,
  books: [],
  knowledge_bases: [],
  skills: [],
  models: { llm: [] },
  perks: [],
  tag: null,
  recommended: false,
  published: true,
};

export function emptyPlan(): AdminPlan {
  return structuredClone(EMPTY_PLAN);
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown; message?: unknown };
    if (typeof data.detail === "string" && data.detail) return data.detail;
    if (typeof data.message === "string" && data.message) return data.message;
  } catch {
    /* keep the fallback */
  }
  return fallback;
}

export async function fetchPlans(): Promise<AdminPlan[]> {
  const res = await apiFetch(apiUrl("/api/payment/admin/plans"));
  if (!res.ok) throw new Error(await readError(res, "Failed to load plans"));
  const data = (await res.json()) as PlanListResponse;
  return data.plans ?? [];
}

export async function createPlan(plan: AdminPlan): Promise<AdminPlan> {
  const res = await apiFetch(apiUrl("/api/payment/admin/plans"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
  if (!res.ok) throw new Error(await readError(res, "Failed to create plan"));
  const data = (await res.json()) as PlanDetailResponse;
  return data.plan;
}

export async function updatePlan(
  planId: string,
  plan: AdminPlan,
): Promise<AdminPlan> {
  const res = await apiFetch(
    apiUrl(`/api/payment/admin/plans/${encodeURIComponent(planId)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan: { ...plan, id: planId },
      }),
    },
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to update plan"));
  const data = (await res.json()) as PlanDetailResponse;
  return data.plan;
}

export async function deletePlan(planId: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/payment/admin/plans/${encodeURIComponent(planId)}`),
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to delete plan"));
}

// ---------------------------------------------------------------------------
// Order ledger
// ---------------------------------------------------------------------------

export type AdminOrderStatus =
  | "pending"
  | "paid"
  | "granted"
  | "completed"
  | "expired"
  | "refunded"
  | "failed";

export interface AdminOrder {
  order_id: string;
  order_no?: string;
  user_id?: string;
  username?: string;
  plan_id?: string;
  plan_name?: string;
  gateway?: string;
  amount_fen?: number;
  currency?: string;
  status?: string;
  expires_at?: string;
  created_at?: string;
  paid_at?: string;
  granted_at?: string;
  refunded_at?: string;
  notify_count?: number;
  last_error?: string;
  plan_snapshot?: Record<string, unknown>;
}

export interface OrderListResponse {
  orders: AdminOrder[];
  count: number;
}

export interface OrderFilters {
  user_id?: string;
  status?: string;
  gateway?: string;
  limit?: number;
  offset?: number;
}

export async function fetchOrders(filters: OrderFilters = {}): Promise<AdminOrder[]> {
  const params = new URLSearchParams();
  if (filters.user_id) params.set("user_id", filters.user_id);
  if (filters.status) params.set("status", filters.status);
  if (filters.gateway) params.set("gateway", filters.gateway);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const qs = params.toString();
  const res = await apiFetch(apiUrl(`/api/payment/admin/orders${qs ? `?${qs}` : ""}`));
  if (!res.ok) throw new Error(await readError(res, "Failed to load orders"));
  const data = (await res.json()) as OrderListResponse;
  return data.orders ?? [];
}

export async function refundOrder(
  orderId: string,
  reason = "",
): Promise<AdminOrder> {
  const res = await apiFetch(
    apiUrl(`/api/payment/admin/orders/${encodeURIComponent(orderId)}/refund`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    },
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to refund order"));
  const data = (await res.json()) as { order: AdminOrder };
  return data.order;
}

// ---------------------------------------------------------------------------
// CDK card keys
// ---------------------------------------------------------------------------

export interface CdkBatch {
  id: string;
  plan?: { id?: string; name?: string } | null;
  count?: number;
  expires_in_days?: number | null;
  expires_at?: string | null;
  created_by?: string;
  created_at?: string;
  redeemed_count?: number;
  total_codes?: number;
  expired_count?: number;
  active_codes?: number;
}

export interface CdkGenerateRequest {
  plan?: { id?: string; name?: string } | null;
  count: number;
  expires_in_days?: number | null;
}

export interface CdkGenerateResponse {
  batch_id: string;
  batch: CdkBatch;
  /** Raw plain codes — returned exactly once at generation time. */
  codes: string[];
}

export interface CdkBatchCodeRecord {
  digest: string;
  status?: string;
  expires_at?: string;
  redeemed_at?: string;
  redeemed_by?: string;
  [key: string]: unknown;
}

export async function fetchCdkBatches(): Promise<CdkBatch[]> {
  const res = await apiFetch(apiUrl("/api/payment/cdk/batches"));
  if (!res.ok) throw new Error(await readError(res, "Failed to load CDK batches"));
  const data = (await res.json()) as CdkBatch[];
  return Array.isArray(data) ? data : [];
}

export async function generateCdkBatch(
  payload: CdkGenerateRequest,
): Promise<CdkGenerateResponse> {
  const res = await apiFetch(apiUrl("/api/payment/cdk/batches"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readError(res, "Failed to generate card keys"));
  return (await res.json()) as CdkGenerateResponse;
}

export async function fetchCdkBatchCodes(
  batchId: string,
  includeRedeemed = true,
): Promise<CdkBatchCodeRecord[]> {
  const qs = includeRedeemed ? "" : "?include_redeemed=false";
  const res = await apiFetch(
    apiUrl(`/api/payment/cdk/batches/${encodeURIComponent(batchId)}/codes${qs}`),
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to load card keys"));
  const data = (await res.json()) as CdkBatchCodeRecord[];
  return Array.isArray(data) ? data : [];
}

/**
 * One-click CSV export of a batch's plain codes.  Triggers a browser
 * download built from the authenticated response (the endpoint sets
 * `Content-Disposition: attachment`).
 */
export async function exportCdkBatchCsv(batchId: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/payment/cdk/batches/${encodeURIComponent(batchId)}/export?fmt=csv`),
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to export card keys"));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `cdk_${batchId}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Client-side CSV export for codes returned straight from generation. */
export function downloadCodesCsv(codes: string[], filename: string): void {
  const header = "code\n";
  const body = codes.map((code) => code).join("\n");
  const blob = new Blob([header + body], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Formatting helpers (pure — unit-testable)
// ---------------------------------------------------------------------------

/** `1290` → `¥12.90`; drops trailing zeros the way the storefront does. */
export function formatPriceFen(priceFen: number): string {
  const yuan = (Number(priceFen) || 0) / 100;
  const fixed = yuan % 1 === 0 ? String(Math.trunc(yuan)) : yuan.toFixed(2);
  return `¥${fixed}`;
}

/** Slugify a plan name into a valid plan id (`[A-Za-z0-9_-]{1,64}`). */
export function slugifyPlanName(name: string): string {
  const slug = (name || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug ? slug.slice(0, 64) : "";
}
"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import {
  fetchOrders,
  refundOrder,
  formatPriceFen,
  type AdminOrder,
  type AdminOrderStatus,
} from "@/lib/payment-admin-api";
import { formatDate as formatLocaleDate, type Language } from "@/lib/datetime";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  ArrowLeft,
  CreditCard,
  RefreshCw,
  Undo2,
  Search,
  Receipt,
} from "lucide-react";
import Link from "next/link";

const STATUSES: Array<{ value: AdminOrderStatus; label: string }> = [
  { value: "pending", label: "Pending" },
  { value: "paid", label: "Paid" },
  { value: "granted", label: "Granted" },
  { value: "completed", label: "Completed" },
  { value: "expired", label: "Expired" },
  { value: "refunded", label: "Refunded" },
  { value: "failed", label: "Failed" },
];

const GATEWAYS = [
  { value: "wechat", label: "WeChat" },
  { value: "epay", label: "EPay" },
];

function formatDate(iso: string | undefined, lang: Language): string {
  if (!iso) return "—";
  try {
    return formatLocaleDate(new Date(iso), lang);
  } catch {
    return "—";
  }
}

function statusTone(status: string | undefined): string {
  switch (status) {
    case "paid":
    case "granted":
    case "completed":
      return "bg-green-500/15 text-green-600 dark:text-green-400";
    case "refunded":
      return "bg-orange-500/15 text-orange-600 dark:text-orange-400";
    case "expired":
    case "failed":
      return "bg-red-500/15 text-red-600 dark:text-red-400";
    default:
      return "bg-[var(--muted)]/50 text-[var(--muted-foreground)]";
  }
}

export default function OrderAuditPage() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const lang: Language = i18n.language?.startsWith("zh") ? "zh" : "en";
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [gatewayFilter, setGatewayFilter] = useState("");
  const [refundTarget, setRefundTarget] = useState<AdminOrder | null>(null);
  const [refundBusy, setRefundBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(
    async (status = "", gateway = "") => {
      setLoading(true);
      setError("");
      try {
        const rows = await fetchOrders({
          status: status || undefined,
          gateway: gateway || undefined,
          limit: 300,
        });
        setOrders(rows);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("Failed to load orders"));
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    fetchAuthStatus().then((status) => {
      if (!status?.authenticated) {
        router.replace("/login");
        return;
      }
      if (status.role !== "admin") {
        router.replace("/");
        return;
      }
      void load();
    });
  }, [router, load]);

  const filteredOrders = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return orders;
    return orders.filter((order) => {
      const haystack = [
        order.order_id,
        order.order_no,
        order.username,
        order.user_id,
        order.plan_name,
        order.plan_id,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [orders, query]);

  async function handleRefund() {
    if (!refundTarget || refundBusy) return;
    setRefundBusy(true);
    try {
      const updated = await refundOrder(refundTarget.order_id);
      setOrders((current) =>
        current.map((o) =>
          o.order_id === updated.order_id ? updated : o,
        ),
      );
      setRefundTarget(null);
      setMessage(t("Order refunded."));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to refund order"));
      setRefundTarget(null);
    } finally {
      setRefundBusy(false);
    }
  }

  const summary = useMemo(() => {
    const total = orders.length;
    const paid = orders.filter((o) =>
      ["paid", "granted", "completed"].includes(o.status ?? ""),
    ).length;
    const refunded = orders.filter((o) => o.status === "refunded").length;
    const revenueFen = orders
      .filter((o) => ["paid", "granted", "completed"].includes(o.status ?? ""))
      .reduce((sum, o) => sum + (o.amount_fen ?? 0), 0);
    return { total, paid, refunded, revenueFen };
  }, [orders]);

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-5xl">
        {/* Header */}
        <div className="mb-8">
          <Link
            href="/admin"
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={16} />
            {t("Back to Admin")}
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <Receipt size={18} className="text-[var(--muted-foreground)]" />
                <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                  {t("Order Audit")}
                </h1>
              </div>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t("All student payment orders — payment status, fulfilment and refunds.")}
              </p>
            </div>
            <button
              onClick={() => void load()}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                         border border-[var(--border)] text-[var(--muted-foreground)]
                         hover:text-[var(--foreground)] hover:bg-[var(--card)]
                         disabled:opacity-50 transition-colors"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              {t("Refresh")}
            </button>
          </div>
        </div>

        {/* Summary strip */}
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: t("Total orders"), value: summary.total },
            { label: t("Paid / fulfilled"), value: summary.paid },
            { label: t("Refunded"), value: summary.refunded },
            { label: t("Revenue"), value: formatPriceFen(summary.revenueFen) },
          ].map((item) => (
            <div
              key={item.label}
              className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3"
            >
              <p className="text-xs text-[var(--muted-foreground)]">{item.label}</p>
              <p className="mt-0.5 text-lg font-semibold text-[var(--foreground)]">
                {item.value}
              </p>
            </div>
          ))}
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {message && (
          <div className="mb-4 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-600 dark:text-green-400">
            {message}
          </div>
        )}

        {/* Filters */}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-1">
            <Search
              size={14}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("Search order / user / plan…")}
              aria-label={t("Search orders")}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] py-2 pl-9 pr-3 text-sm
                         text-[var(--foreground)] placeholder:text-[var(--muted-foreground)]/70
                         outline-none focus:border-[var(--ring)] transition-colors"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              void load(e.target.value, gatewayFilter);
            }}
            aria-label={t("Filter by status")}
            className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm
                       text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
          >
            <option value="">{t("All statuses")}</option>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {t(s.label)}
              </option>
            ))}
          </select>
          <select
            value={gatewayFilter}
            onChange={(e) => {
              setGatewayFilter(e.target.value);
              void load(statusFilter, e.target.value);
            }}
            aria-label={t("Filter by gateway")}
            className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm
                       text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
          >
            <option value="">{t("All gateways")}</option>
            {GATEWAYS.map((g) => (
              <option key={g.value} value={g.value}>
                {t(g.label)}
              </option>
            ))}
          </select>
          <span className="text-xs text-[var(--muted-foreground)]">
            {t("{{count}} shown", { count: filteredOrders.length })}
          </span>
        </div>

        <div className="overflow-x-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
          {loading ? (
            <div className="divide-y divide-[var(--border)]" aria-hidden>
              {[0, 1, 2, 3].map((row) => (
                <div
                  key={row}
                  className="flex animate-pulse items-center gap-3 px-5 py-4"
                >
                  <div className="h-3 w-32 rounded bg-[var(--muted)]/60" />
                  <div className="h-3 w-20 rounded bg-[var(--muted)]/40" />
                  <div className="h-5 w-16 rounded-full bg-[var(--muted)]/40" />
                </div>
              ))}
            </div>
          ) : filteredOrders.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <CreditCard
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No orders found")}
              </p>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t("Orders created by learners will appear here.")}
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                  <th className="px-5 py-3 font-medium">{t("Order")}</th>
                  <th className="px-5 py-3 font-medium">{t("Student")}</th>
                  <th className="px-5 py-3 font-medium">{t("Plan")}</th>
                  <th className="px-5 py-3 font-medium">{t("Gateway")}</th>
                  <th className="px-5 py-3 font-medium text-right">{t("Amount")}</th>
                  <th className="px-5 py-3 font-medium">{t("Status")}</th>
                  <th className="px-5 py-3 font-medium">{t("Created")}</th>
                  <th className="px-5 py-3 font-medium text-right">{t("Actions")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filteredOrders.map((order) => {
                  const refundable =
                    order.status === "paid" ||
                    order.status === "granted" ||
                    order.status === "completed";
                  return (
                    <tr key={order.order_id} className="hover:bg-[var(--background)]/50 transition-colors">
                      <td className="px-5 py-3">
                        <p className="font-mono text-xs text-[var(--foreground)]">
                          {order.order_no ?? order.order_id}
                        </p>
                        <p className="text-[11px] text-[var(--muted-foreground)]">
                          {order.order_id}
                        </p>
                      </td>
                      <td className="px-5 py-3">
                        <p className="text-[var(--foreground)]">
                          {order.username || "—"}
                        </p>
                        <p className="text-[11px] text-[var(--muted-foreground)]">
                          {order.user_id ? order.user_id.slice(0, 8) : ""}
                        </p>
                      </td>
                      <td className="px-5 py-3 text-[var(--foreground)]">
                        {order.plan_name || order.plan_id || "—"}
                      </td>
                      <td className="px-5 py-3">
                        <span className="text-[var(--muted-foreground)]">
                          {order.gateway === "wechat"
                            ? t("WeChat")
                            : order.gateway === "epay"
                              ? t("EPay")
                              : order.gateway || "—"}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-right font-medium text-[var(--foreground)]">
                        {formatPriceFen(order.amount_fen ?? 0)}
                      </td>
                      <td className="px-5 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusTone(
                            order.status,
                          )}`}
                        >
                          {t(
                            order.status === "pending"
                              ? "Pending"
                              : order.status === "paid"
                                ? "Paid"
                                : order.status === "granted"
                                  ? "Granted"
                                  : order.status === "completed"
                                    ? "Completed"
                                    : order.status === "expired"
                                      ? "Expired"
                                      : order.status === "refunded"
                                        ? "Refunded"
                                        : order.status === "failed"
                                          ? "Failed"
                                          : String(order.status ?? "—"),
                          )}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-[var(--muted-foreground)]">
                        {formatDate(order.created_at, lang)}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center justify-end gap-1.5">
                          {refundable && (
                            <button
                              onClick={() => setRefundTarget(order)}
                              title={t("Mark refunded")}
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                       hover:bg-orange-500/10 hover:text-orange-500 transition-colors"
                            >
                              <Undo2 size={15} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <p className="mt-8 text-center text-xs text-[var(--muted-foreground)]">
          {t("DeepTutor Admin · Order Audit")}
        </p>
      </div>

      <ConfirmDialog
        open={refundTarget !== null}
        title={t("Mark order refunded")}
        tone="danger"
        confirmLabel={t("Mark refunded")}
        busyLabel={t("Refunding…")}
        busy={refundBusy}
        onConfirm={handleRefund}
        onCancel={() => setRefundTarget(null)}
      >
        {refundTarget && (
          <p>
            {t(
              "Mark order {{order}} refunded? The learner's access is left unchanged; this only records the refund on the ledger.",
              { order: refundTarget.order_no ?? refundTarget.order_id },
            )}
          </p>
        )}
      </ConfirmDialog>
    </div>
  );
}
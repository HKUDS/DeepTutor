"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import {
  fetchCdkBatches,
  fetchCdkBatchCodes,
  generateCdkBatch,
  exportCdkBatchCsv,
  downloadCodesCsv,
  formatPriceFen,
  type CdkBatch,
  type CdkGenerateResponse,
} from "@/lib/payment-admin-api";
import { fetchPlans, type AdminPlan } from "@/lib/payment-admin-api";
import { formatDate as formatLocaleDate, type Language } from "@/lib/datetime";
import {
  ArrowLeft,
  KeyRound,
  Loader2,
  RefreshCw,
  Download,
  Plus,
  X,
  Copy,
  Check,
} from "lucide-react";
import Link from "next/link";

function formatDate(iso: string | undefined, lang: Language): string {
  if (!iso) return "—";
  try {
    return formatLocaleDate(new Date(iso), lang);
  } catch {
    return "—";
  }
}

export default function CdkManagementPage() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const lang: Language = i18n.language?.startsWith("zh") ? "zh" : "en";
  const [batches, setBatches] = useState<CdkBatch[]>([]);
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [createPlanId, setCreatePlanId] = useState("");
  const [createCount, setCreateCount] = useState("50");
  const [createDays, setCreateDays] = useState("");
  const [generateError, setGenerateError] = useState("");
  const [generated, setGenerated] = useState<CdkGenerateResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const [viewBatchId, setViewBatchId] = useState<string | null>(null);
  const [batchCodes, setBatchCodes] = useState<
    { digest: string; status?: string; expires_at?: string }[]
  >([]);
  const [batchLoading, setBatchLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextBatches, nextPlans] = await Promise.all([
        fetchCdkBatches(),
        fetchPlans(),
      ]);
      setBatches(nextBatches);
      setPlans(nextPlans);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load card keys"));
    } finally {
      setLoading(false);
    }
  }, [t]);

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

  const planOptions = useMemo(
    () => [...plans].sort((a, b) => (a.price_fen ?? 0) - (b.price_fen ?? 0)),
    [plans],
  );

  function openCreate() {
    setCreatePlanId(planOptions[0]?.id ?? "");
    setCreateCount("50");
    setCreateDays("");
    setGenerateError("");
    setGenerated(null);
    setCreateOpen(true);
  }

  function closeCreate() {
    if (generating) return;
    setCreateOpen(false);
    setGenerated(null);
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    if (generating) return;
    setGenerateError("");
    const count = parseInt(createCount, 10);
    if (!count || count < 1) {
      setGenerateError(t("Count must be at least 1."));
      return;
    }
    if (count > 10000) {
      setGenerateError(t("Count must be 10,000 or fewer."));
      return;
    }
    const selectedPlan = planOptions.find((p) => p.id === createPlanId) ?? null;
    setGenerating(true);
    try {
      const result = await generateCdkBatch({
        plan: selectedPlan ? { id: selectedPlan.id, name: selectedPlan.name } : null,
        count,
        expires_in_days: createDays ? parseInt(createDays, 10) : null,
      });
      setGenerated(result);
      setBatches((current) => [result.batch, ...current]);
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : t("Failed to generate card keys"));
    } finally {
      setGenerating(false);
    }
  }

  async function handleExport(batch: CdkBatch) {
    try {
      await exportCdkBatchCsv(batch.id);
      setMessage(t("CSV exported."));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to export CSV"));
    }
  }

  async function handleDownloadGenerated() {
    if (!generated) return;
    downloadCodesCsv(generated.codes, `cdk_${generated.batch_id}.csv`);
  }

  async function handleCopyAll() {
    if (!generated) return;
    await navigator.clipboard.writeText(generated.codes.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function handleViewBatch(batchId: string) {
    if (viewBatchId === batchId) {
      setViewBatchId(null);
      setBatchCodes([]);
      return;
    }
    setViewBatchId(batchId);
    setBatchLoading(true);
    setError("");
    try {
      const codes = await fetchCdkBatchCodes(batchId);
      setBatchCodes(codes);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load card keys"));
    } finally {
      setBatchLoading(false);
    }
  }

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-4xl">
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
                <KeyRound size={18} className="text-[var(--muted-foreground)]" />
                <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                  {t("Card Key (CDK) Management")}
                </h1>
              </div>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t("Batch-generate single-use card keys and export them as CSV.")}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                onClick={load}
                disabled={loading}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--muted-foreground)]
                           hover:text-[var(--foreground)] hover:bg-[var(--card)]
                           disabled:opacity-50 transition-colors"
              >
                <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
                {t("Refresh")}
              </button>
              <button
                onClick={openCreate}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium
                           bg-[var(--foreground)] text-[var(--background)] hover:opacity-90 transition-opacity"
              >
                <Plus size={14} />
                {t("Generate batch")}
              </button>
            </div>
          </div>
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

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
          {loading ? (
            <div className="divide-y divide-[var(--border)]" aria-hidden>
              {[0, 1, 2].map((row) => (
                <div key={row} className="flex animate-pulse items-center gap-3 px-5 py-4">
                  <div className="h-8 w-8 rounded-lg bg-[var(--muted)]/60" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3 w-36 rounded bg-[var(--muted)]/60" />
                    <div className="h-2.5 w-24 rounded bg-[var(--muted)]/40" />
                  </div>
                </div>
              ))}
            </div>
          ) : batches.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <KeyRound
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No batches yet")}
              </p>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t("Generate a batch of card keys to distribute offline.")}
              </p>
              <button
                onClick={openCreate}
                className="mt-4 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--foreground)]
                           hover:bg-[var(--background)]/60 transition-colors"
              >
                <Plus size={14} />
                {t("Generate batch")}
              </button>
            </div>
          ) : (
            <div className="divide-y divide-[var(--border)]">
              {batches.map((batch) => {
                const plan = batch.plan as { id?: string; name?: string } | null;
                return (
                  <div key={batch.id} className="px-5 py-4 hover:bg-[var(--background)]/50 transition-colors">
                    <div className="flex items-center gap-4">
                      <div className="flex min-w-0 flex-1 items-center gap-3">
                        <div>
                          <p className="text-sm font-medium text-[var(--foreground)]">
                            {plan?.name || batch.plan?.id || t("Generic batch")}
                          </p>
                          <p className="mt-0.5 font-mono text-xs text-[var(--muted-foreground)]">
                            {batch.id}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-[var(--muted-foreground)]">
                        <span>
                          {t("{{active}} active", { active: batch.active_codes ?? 0 })}
                        </span>
                        <span>
                          {t("{{redeemed}} redeemed", { redeemed: batch.redeemed_count ?? 0 })}
                        </span>
                        <span>
                          {t("{{expired}} expired", { expired: batch.expired_count ?? 0 })}
                        </span>
                        <span>{formatDate(batch.created_at, lang)}</span>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <button
                          onClick={() => void handleExport(batch)}
                          title={t("Export CSV")}
                          className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] transition-colors"
                        >
                          <Download size={15} />
                        </button>
                        <button
                          onClick={() => void handleViewBatch(batch.id)}
                          title={t("View codes")}
                          className="rounded-lg px-2 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] transition-colors"
                        >
                          {viewBatchId === batch.id ? t("Hide") : t("View")}
                        </button>
                      </div>
                    </div>
                    {viewBatchId === batch.id && (
                      <div className="mt-3 max-h-64 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--background)]/40 p-2">
                        {batchLoading ? (
                          <div className="flex items-center justify-center py-6">
                            <Loader2 size={18} className="animate-spin text-[var(--muted-foreground)]" />
                          </div>
                        ) : batchCodes.length === 0 ? (
                          <p className="py-4 text-center text-xs text-[var(--muted-foreground)]">
                            {t("No codes in this batch.")}
                          </p>
                        ) : (
                          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2 lg:grid-cols-3">
                            {batchCodes.map((code) => (
                              <div
                                key={code.digest}
                                className="flex items-center justify-between rounded-md px-2 py-1 font-mono text-[11px] text-[var(--foreground)]"
                              >
                                <span>{code.digest.slice(0, 12)}…</span>
                                <span
                                  className={
                                    code.status === "redeemed"
                                      ? "text-orange-500"
                                      : "text-green-500"
                                  }
                                >
                                  {code.status ?? "unused"}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <p className="mt-8 text-center text-xs text-[var(--muted-foreground)]">
          {t("DeepTutor Admin · Card Key Management")}
        </p>
      </div>

      {createOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[var(--overlay)] px-4 py-8"
          role="dialog"
          aria-modal="true"
          onClick={closeCreate}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold text-[var(--foreground)]">
                {t("Generate card keys")}
              </h2>
              <button
                type="button"
                onClick={closeCreate}
                disabled={generating}
                className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] disabled:opacity-40"
                aria-label={t("Close")}
              >
                <X size={16} />
              </button>
            </div>

            {generated ? (
              <div>
                <div className="rounded-xl border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-600 dark:text-green-400">
                  {t("Batch {{id}} generated with {{count}} codes.", {
                    id: generated.batch_id,
                    count: generated.codes.length,
                  })}
                </div>
                <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                  {t(
                    "The plain codes are shown once — save them now. Subsequent reads only expose digests.",
                  )}
                </p>
                <div className="mt-3 max-h-48 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--background)]/40 p-3 font-mono text-xs leading-relaxed text-[var(--foreground)]">
                  {generated.codes.slice(0, 100).join("\n")}
                  {generated.codes.length > 100 &&
                    `\n… and ${generated.codes.length - 100} more`}
                </div>
                <div className="mt-4 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => void handleCopyAll()}
                    className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--foreground)] hover:bg-[var(--background)]/60"
                  >
                    {copied ? (
                      <Check size={14} className="text-green-500" />
                    ) : (
                      <Copy size={14} />
                    )}
                    {copied ? t("Copied") : t("Copy all")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDownloadGenerated()}
                    className="flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90"
                  >
                    <Download size={14} />
                    {t("Download CSV")}
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleGenerate}>
                <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
                  {t("Bind plan")}
                  <select
                    value={createPlanId}
                    onChange={(e) => setCreatePlanId(e.target.value)}
                    disabled={generating}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
                  >
                    <option value="">{t("No plan (generic)")}</option>
                    {planOptions.map((plan) => (
                      <option key={plan.id} value={plan.id}>
                        {plan.name} · {formatPriceFen(plan.price_fen)}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
                  {t("Count")}
                  <input
                    type="number"
                    min="1"
                    max="10000"
                    value={createCount}
                    onChange={(e) => setCreateCount(e.target.value)}
                    disabled={generating}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
                  />
                </label>

                <label className="mb-4 block text-xs text-[var(--muted-foreground)]">
                  {t("Valid days (optional)")}
                  <input
                    type="number"
                    min="1"
                    value={createDays}
                    onChange={(e) => setCreateDays(e.target.value)}
                    disabled={generating}
                    placeholder={t("Leave empty for no expiry")}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
                  />
                </label>

                {generateError && (
                  <p className="mb-3 text-xs text-red-500">{generateError}</p>
                )}

                <div className="flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={closeCreate}
                    disabled={generating}
                    className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
                  >
                    {t("Cancel")}
                  </button>
                  <button
                    type="submit"
                    disabled={generating}
                    className="flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-40"
                  >
                    {generating ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <KeyRound size={14} />
                    )}
                    {generating ? t("Generating…") : t("Generate")}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
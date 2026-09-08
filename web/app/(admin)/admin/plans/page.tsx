"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import {
  fetchPlans,
  createPlan,
  updatePlan,
  deletePlan,
  emptyPlan,
  slugifyPlanName,
  formatPriceFen,
  type AdminPlan,
  type AdminPlanModelEntry,
  type AdminPlanKnowledgeBase,
} from "@/lib/payment-admin-api";
import { fetchAdminResources, fetchAdminBooks } from "@/features/multi-user/api";
import type {
  MultiUserResources,
  AdminBook,
} from "@/features/multi-user/types";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  ArrowLeft,
  Package,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  Pencil,
  Loader2,
  X,
  BookOpen,
  Database,
  Cpu,
  Check,
} from "lucide-react";
import Link from "next/link";

type SaveState = "idle" | "saving" | "saved" | "error";

const PERIODS = ["monthly", "quarterly", "yearly", "lifetime"] as const;

function periodDays(period: string, durationDays?: number | null): number | null {
  if (period === "lifetime") return null;
  if (durationDays && Number(durationDays) > 0) return Number(durationDays);
  if (period === "monthly") return 30;
  if (period === "quarterly") return 90;
  if (period === "yearly") return 365;
  return null;
}

function PlanEditor({
  initial,
  resources,
  books,
  onSave,
  onCancel,
}: {
  initial: AdminPlan;
  resources: MultiUserResources | null;
  books: AdminBook[];
  onSave: (plan: AdminPlan) => Promise<void>;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const isNew = !initial.id;
  const [plan, setPlan] = useState<AdminPlan>(() => {
    const base = isNew ? emptyPlan() : structuredClone(initial);
    return {
      ...base,
      duration_days:
        base.duration_days ?? periodDays(base.period, base.duration_days),
    };
  });
  const [priceYuan, setPriceYuan] = useState<string>(
    ((initial.price_fen ?? 0) / 100).toString(),
  );
  const [nameTouched, setNameTouched] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const modelProfiles = resources?.models?.llm ?? [];

  function update(patch: Partial<AdminPlan>) {
    setPlan((current) => ({ ...current, ...patch }));
  }

  function toggleIdFromName(value: string) {
    update({ name: value });
    if (!nameTouched) {
      update({ id: slugifyPlanName(value) });
    }
  }

  function handlePeriodChange(period: AdminPlan["period"]) {
    update({
      period,
      duration_days:
        period === "lifetime" ? null : periodDays(period, plan.duration_days),
    });
  }

  function toggleBook(bookId: string) {
    const exists = plan.books.includes(bookId);
    update({
      books: exists
        ? plan.books.filter((id) => id !== bookId)
        : [...plan.books, bookId],
    });
  }

  function toggleKb(resourceId: string, name: string) {
    const exists = plan.knowledge_bases.some((kb) => kb.name === resourceId);
    let next: AdminPlanKnowledgeBase[];
    if (exists) {
      next = plan.knowledge_bases.filter((kb) => kb.name !== resourceId);
    } else {
      // The cashier binds KB grants by the `admin:kb:` resource id.
      next = [...plan.knowledge_bases, { name: resourceId }];
    }
    update({ knowledge_bases: next });
  }

  function toggleModel(profileId: string, modelId: string) {
    const entries = plan.models.llm;
    const existing = entries.find((entry) => entry.profile_id === profileId);
    let next: AdminPlanModelEntry[];
    if (existing) {
      const modelIds = new Set(existing.model_ids);
      if (modelIds.has(modelId)) modelIds.delete(modelId);
      else modelIds.add(modelId);
      next = entries
        .map((entry) =>
          entry.profile_id === profileId
            ? { ...entry, model_ids: Array.from(modelIds) }
            : entry,
        )
        .filter((entry) => entry.model_ids.length > 0);
    } else {
      next = [
        ...entries,
        { profile_id: profileId, model_ids: [modelId] },
      ];
    }
    update({ models: { llm: next } });
  }

  function hasModel(profileId: string, modelId: string): boolean {
    return plan.models.llm.some(
      (entry) =>
        entry.profile_id === profileId &&
        Array.isArray(entry.model_ids) &&
        entry.model_ids.includes(modelId),
    );
  }

  function togglePerk(perk: string) {
    const perks = plan.perks ?? [];
    const exists = perks.includes(perk);
    update({ perks: exists ? perks.filter((p) => p !== perk) : [...perks, perk] });
  }

  function handlePerkInput(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const value = (e.target as HTMLInputElement).value.trim();
    if (!value) return;
    if (!(plan.perks ?? []).includes(value)) {
      update({ perks: [...(plan.perks ?? []), value] });
    }
    (e.target as HTMLInputElement).value = "";
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (saving) return;
    setError("");
    const priceFen = Math.round((parseFloat(priceYuan) || 0) * 100);
    if (!plan.id.trim() || !plan.name.trim()) {
      setError(t("A plan needs an id and a name."));
      return;
    }
    if (priceFen <= 0) {
      setError(t("A non-zero price is required."));
      return;
    }
    const finalPlan: AdminPlan = {
      ...plan,
      price_fen: priceFen,
      duration_days:
        plan.period === "lifetime" ? null : periodDays(plan.period, plan.duration_days),
    };
    setSaving(true);
    try {
      await onSave(finalPlan);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Failed to save plan"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[var(--overlay)] px-4 py-8"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl"
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-base font-semibold text-[var(--foreground)]">
            {isNew ? t("Create plan") : t("Edit plan")}
          </h2>
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] disabled:opacity-40"
            aria-label={t("Close")}
          >
            <X size={16} />
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block text-xs text-[var(--muted-foreground)]">
            {t("Plan name")}
            <input
              type="text"
              value={plan.name}
              onChange={(e) => toggleIdFromName(e.target.value)}
              disabled={saving}
              className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
            />
          </label>
          <label className="block text-xs text-[var(--muted-foreground)]">
            {t("Plan ID")}
            <input
              type="text"
              value={plan.id}
              onChange={(e) => {
                setNameTouched(true);
                update({ id: e.target.value });
              }}
              disabled={saving || !isNew}
              className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)] disabled:opacity-50"
            />
            {!isNew && (
              <span className="mt-1 block text-[11px] text-[var(--muted-foreground)]/70">
                {t("ID is fixed after creation.")}
              </span>
            )}
          </label>
          <label className="block text-xs text-[var(--muted-foreground)]">
            {t("Price (yuan)")}
            <input
              type="number"
              min="0"
              step="0.01"
              value={priceYuan}
              onChange={(e) => setPriceYuan(e.target.value)}
              disabled={saving}
              className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
            />
          </label>
          <label className="block text-xs text-[var(--muted-foreground)]">
            {t("Validity")}
            <select
              value={plan.period}
              onChange={(e) => handlePeriodChange(e.target.value as AdminPlan["period"])}
              disabled={saving}
              className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
            >
              {PERIODS.map((period) => (
                <option key={period} value={period}>
                  {t(period)}
                </option>
              ))}
            </select>
          </label>
          {plan.period !== "lifetime" && (
            <label className="block text-xs text-[var(--muted-foreground)] sm:col-span-2">
              {t("Duration (days, optional — defaults to the period)")}
              <input
                type="number"
                min="1"
                value={plan.duration_days ?? ""}
                onChange={(e) =>
                  update({ duration_days: e.target.value ? Number(e.target.value) : null })
                }
                disabled={saving}
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
            </label>
          )}
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <label className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
            <input
              type="checkbox"
              checked={plan.recommended}
              onChange={(e) => update({ recommended: e.target.checked })}
              disabled={saving}
              className="accent-[var(--primary)]"
            />
            {t("Recommended")}
          </label>
          <label className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
            <input
              type="checkbox"
              checked={plan.published}
              onChange={(e) => update({ published: e.target.checked })}
              disabled={saving}
              className="accent-[var(--primary)]"
            />
            {t("Published")}
          </label>
        </div>

        <label className="mt-4 block text-xs text-[var(--muted-foreground)]">
          {t("Badge tag (optional)")}
          <input
            type="text"
            value={plan.tag ?? ""}
            onChange={(e) => update({ tag: e.target.value.trim() || null })}
            disabled={saving}
            placeholder={t("e.g. Most popular")}
            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
          />
        </label>

        {/* Perks */}
        <div className="mt-5">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Feature bullets")}
          </h3>
          {((plan.perks ?? []) as string[]).length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {(plan.perks ?? []).map((perk) => (
                <span
                  key={perk}
                  className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--background)]/50 px-2 py-0.5 text-xs text-[var(--foreground)]"
                >
                  {perk}
                  <button
                    type="button"
                    onClick={() => togglePerk(perk)}
                    disabled={saving}
                    className="text-[var(--muted-foreground)] hover:text-red-500"
                    aria-label={t("Remove {{perk}}", { perk })}
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <input
            type="text"
            onKeyDown={handlePerkInput}
            disabled={saving}
            placeholder={t("Add a bullet and press Enter…")}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
          />
        </div>

        {/* Permission bundle */}
        <div className="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-3">
          <div>
            <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              <BookOpen size={13} />
              {t("Books")}
            </h3>
            <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-[var(--border)] p-2">
              {books.length === 0 ? (
                <p className="px-1 py-2 text-xs text-[var(--muted-foreground)]">
                  {t("No shared books yet")}
                </p>
              ) : (
                books.map((book) => {
                  const checked = plan.books.includes(book.book_id);
                  return (
                    <label
                      key={book.book_id}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs text-[var(--foreground)] hover:bg-[var(--background)]/60"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleBook(book.book_id)}
                        disabled={saving}
                        className="accent-[var(--primary)]"
                      />
                      <span className="min-w-0 flex-1 truncate">{book.title}</span>
                      {checked && <Check size={13} className="text-[var(--primary)]" />}
                    </label>
                  );
                })
              )}
            </div>
          </div>

          <div>
            <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              <Database size={13} />
              {t("Knowledge bases")}
            </h3>
            <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-[var(--border)] p-2">
              {(resources?.knowledge_bases ?? []).length === 0 ? (
                <p className="px-1 py-2 text-xs text-[var(--muted-foreground)]">
                  {t("No knowledge bases available")}
                </p>
              ) : (
                (resources?.knowledge_bases ?? []).map((kb) => {
                  const checked = plan.knowledge_bases.some(
                    (item) => item.name === kb.resource_id,
                  );
                  return (
                    <label
                      key={kb.resource_id}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs text-[var(--foreground)] hover:bg-[var(--background)]/60"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleKb(kb.resource_id, kb.name)}
                        disabled={saving}
                        className="accent-[var(--primary)]"
                      />
                      <span className="min-w-0 flex-1 truncate">{kb.name}</span>
                      {checked && <Check size={13} className="text-[var(--primary)]" />}
                    </label>
                  );
                })
              )}
            </div>
          </div>

          <div>
            <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              <Cpu size={13} />
              {t("Model whitelist")}
            </h3>
            <div className="max-h-56 overflow-y-auto rounded-lg border border-[var(--border)] p-2">
              {modelProfiles.length === 0 ? (
                <p className="px-1 py-2 text-xs text-[var(--muted-foreground)]">
                  {t("No assignable model profiles")}
                </p>
              ) : (
                modelProfiles.map((profile) => (
                  <div key={profile.profile_id} className="py-1">
                    <p className="px-2 text-xs font-medium text-[var(--foreground)]">
                      {profile.name}
                    </p>
                    <div className="mt-0.5 space-y-0.5">
                      {(profile.models ?? []).map((model) => {
                        const checked = hasModel(profile.profile_id, model.model_id);
                        return (
                          <label
                            key={model.model_id}
                            className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleModel(profile.profile_id, model.model_id)}
                              disabled={saving}
                              className="accent-[var(--primary)]"
                            />
                            <span className="min-w-0 flex-1 truncate">
                              {model.name || model.model_id}
                            </span>
                          </label>
                        );
                      })}
                      {(profile.models ?? []).length === 0 && (
                        <p className="px-2 text-[11px] text-[var(--muted-foreground)]/60">
                          {t("No models")}
                        </p>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {error && (
          <p className="mt-4 text-xs text-red-500">{error}</p>
        )}

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
          >
            {t("Cancel")}
          </button>
          <button
            type="submit"
            disabled={saving}
            className="flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-40"
          >
            {saving ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Save size={14} />
            )}
            {isNew ? t("Create") : t("Save changes")}
          </button>
        </div>
      </div>
    </form>
  );
}

export default function PlansPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [resources, setResources] = useState<MultiUserResources | null>(null);
  const [books, setBooks] = useState<AdminBook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editor, setEditor] = useState<AdminPlan | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AdminPlan | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextPlans, nextResources, nextBooks] = await Promise.all([
        fetchPlans(),
        fetchAdminResources(),
        fetchAdminBooks(),
      ]);
      setPlans(nextPlans);
      setResources(nextResources);
      setBooks(nextBooks);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load plans"));
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

  async function handleSavePlan(plan: AdminPlan) {
    if (plan.id && plans.some((p) => p.id === plan.id)) {
      await updatePlan(plan.id, plan);
    } else {
      await createPlan(plan);
    }
    setEditor(null);
    setCreateOpen(false);
    setMessage(
      plan.id && plans.some((p) => p.id === plan.id)
        ? t("Plan updated.")
        : t("Plan created."),
    );
    await load();
  }

  async function handleDelete() {
    if (!deleteTarget || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await deletePlan(deleteTarget.id);
      setPlans((current) => current.filter((p) => p.id !== deleteTarget.id));
      setDeleteTarget(null);
      setMessage(t("Plan deleted."));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to delete plan"));
      setDeleteTarget(null);
    } finally {
      setDeleteBusy(false);
    }
  }

  const sortedPlans = useMemo(
    () =>
      [...plans].sort((a, b) => {
        // Published first, then recommended, then by price.
        if (Boolean(a.published) !== Boolean(b.published))
          return a.published ? -1 : 1;
        if (Boolean(a.recommended) !== Boolean(b.recommended))
          return a.recommended ? -1 : 1;
        return (a.price_fen ?? 0) - (b.price_fen ?? 0);
      }),
    [plans],
  );

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
                <Package size={18} className="text-[var(--muted-foreground)]" />
                <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                  {t("Plan Management")}
                </h1>
              </div>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t("Pricing plans, validity and the books / knowledge bases / models each purchase unlocks.")}
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
                onClick={() => setCreateOpen(true)}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium
                           bg-[var(--foreground)] text-[var(--background)] hover:opacity-90 transition-opacity"
              >
                <Plus size={14} />
                {t("New plan")}
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
                <div
                  key={row}
                  className="flex animate-pulse items-center gap-3 px-5 py-4"
                >
                  <div className="h-8 w-8 rounded-lg bg-[var(--muted)]/60" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3 w-36 rounded bg-[var(--muted)]/60" />
                    <div className="h-2.5 w-24 rounded bg-[var(--muted)]/40" />
                  </div>
                </div>
              ))}
            </div>
          ) : sortedPlans.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <Package
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No plans yet")}
              </p>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t("Create a pricing plan to start selling access.")}
              </p>
              <button
                onClick={() => setCreateOpen(true)}
                className="mt-4 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--foreground)]
                           hover:bg-[var(--background)]/60 transition-colors"
              >
                <Plus size={14} />
                {t("New plan")}
              </button>
            </div>
          ) : (
            <div className="divide-y divide-[var(--border)]">
              {sortedPlans.map((plan) => (
                <div
                  key={plan.id}
                  className="flex items-center gap-4 px-5 py-4 hover:bg-[var(--background)]/50 transition-colors"
                >
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <div>
                      <p className="truncate text-sm font-medium text-[var(--foreground)]">
                        {plan.name}
                        {!plan.published && (
                          <span className="ml-2 rounded-full bg-[var(--muted)]/50 px-2 py-0.5 text-[11px] font-normal text-[var(--muted-foreground)]">
                            {t("Draft")}
                          </span>
                        )}
                        {plan.recommended && (
                          <span className="ml-2 rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-normal text-amber-600 dark:text-amber-400">
                            ★ {t("Recommended")}
                          </span>
                        )}
                      </p>
                      <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                        {formatPriceFen(plan.price_fen)} ·{" "}
                        {plan.period === "lifetime"
                          ? t("lifetime")
                          : t("{{days}} days", { days: plan.duration_days ?? periodDays(plan.period, plan.duration_days) })}
                        {" · "}
                        {t("{{books}} books", { books: plan.books.length })}
                        {" · "}
                        {t("{{kbs}} KBs", { kbs: plan.knowledge_bases.length })}
                        {" · "}
                        {t("{{models}} models", {
                          models: plan.models.llm.reduce(
                            (total, entry) => total + entry.model_ids.length,
                            0,
                          ),
                        })}
                        {plan.tag && (
                          <span className="ml-1 text-[11px] text-[var(--primary)]">
                            · {plan.tag}
                          </span>
                        )}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      onClick={() => setEditor(plan)}
                      title={t("Edit plan")}
                      className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] transition-colors"
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      onClick={() => setDeleteTarget(plan)}
                      title={t("Delete plan")}
                      className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-500 transition-colors"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <p className="mt-8 text-center text-xs text-[var(--muted-foreground)]">
          {t("DeepTutor Admin · Plan Management")}
        </p>
      </div>

      {(editor || createOpen) && (
        <PlanEditor
          initial={editor ?? emptyPlan()}
          resources={resources}
          books={books}
          onSave={handleSavePlan}
          onCancel={() => {
            setEditor(null);
            setCreateOpen(false);
          }}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title={t("Delete plan")}
        tone="danger"
        confirmLabel={t("Delete plan")}
        busyLabel={t("Deleting…")}
        busy={deleteBusy}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      >
        {deleteTarget && (
          <p>
            {t(
              "Delete “{{name}}”? Existing orders keep their plan snapshot, but the plan is no longer purchasable.",
              { name: deleteTarget.name },
            )}
          </p>
        )}
      </ConfirmDialog>
    </div>
  );
}
"use client";

import { Fragment, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import {
  listUsers,
  deleteUser,
  setUserRole,
  createUser,
  fetchDefaultQuota,
  saveDefaultQuota,
  type ResourceQuota,
  type UserRecord,
} from "@/lib/admin-api";
import { GrantEditor } from "@/features/multi-user/components/GrantEditor";
import { UserAvatar } from "@/components/UserAvatar";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { filterUsersByQuery } from "@/lib/admin-users";
import {
  Search,
  KeyRound,
  Shield,
  ShieldCheck,
  ShieldOff,
  Trash2,
  RefreshCw,
  ArrowLeft,
  SlidersHorizontal,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { formatDate as formatLocaleDate, type Language } from "@/lib/datetime";
import {
  EMBEDDING_TOKEN_UNIT,
  LLM_TOKEN_UNIT,
  formatQuotaRaw,
  parseQuotaInput,
  quotaInputValue,
} from "@/features/multi-user/quota-ui";

type QuotaDraft = {
  llm: { daily: string; monthly: string };
  embedding: { daily: string; monthly: string };
  mineru: { daily: string; monthly: string; perFile: string };
};

const FALLBACK_DEFAULT_QUOTA: ResourceQuota = {
  llm: { daily_tokens: 100_000, monthly_tokens: 1_000_000 },
  embedding: { daily_tokens: 1_000_000, monthly_tokens: 10_000_000 },
  mineru: { daily_pages: 50, monthly_pages: 500, max_pages_per_file: 50 },
};

function quotaToDraft(quota: ResourceQuota): QuotaDraft {
  return {
    llm: {
      daily: quotaInputValue(quota.llm.daily_tokens, LLM_TOKEN_UNIT),
      monthly: quotaInputValue(quota.llm.monthly_tokens, LLM_TOKEN_UNIT),
    },
    embedding: {
      daily: quotaInputValue(
        quota.embedding.daily_tokens,
        EMBEDDING_TOKEN_UNIT,
      ),
      monthly: quotaInputValue(
        quota.embedding.monthly_tokens,
        EMBEDDING_TOKEN_UNIT,
      ),
    },
    mineru: {
      daily: quotaInputValue(quota.mineru.daily_pages, 1),
      monthly: quotaInputValue(quota.mineru.monthly_pages, 1),
      perFile: quotaInputValue(quota.mineru.max_pages_per_file, 1),
    },
  };
}

function draftToQuota(draft: QuotaDraft): ResourceQuota | null {
  const llmDaily = parseQuotaInput(draft.llm.daily, LLM_TOKEN_UNIT);
  const llmMonthly = parseQuotaInput(draft.llm.monthly, LLM_TOKEN_UNIT);
  const embeddingDaily = parseQuotaInput(
    draft.embedding.daily,
    EMBEDDING_TOKEN_UNIT,
  );
  const embeddingMonthly = parseQuotaInput(
    draft.embedding.monthly,
    EMBEDDING_TOKEN_UNIT,
  );
  const mineruDaily = parseQuotaInput(draft.mineru.daily, 1);
  const mineruMonthly = parseQuotaInput(draft.mineru.monthly, 1);
  const mineruPerFile = parseQuotaInput(draft.mineru.perFile, 1);
  if (
    llmDaily === null ||
    llmMonthly === null ||
    embeddingDaily === null ||
    embeddingMonthly === null ||
    mineruDaily === null ||
    mineruMonthly === null ||
    mineruPerFile === null
  ) {
    return null;
  }
  return {
    llm: { daily_tokens: llmDaily, monthly_tokens: llmMonthly },
    embedding: {
      daily_tokens: embeddingDaily,
      monthly_tokens: embeddingMonthly,
    },
    mineru: {
      daily_pages: mineruDaily,
      monthly_pages: mineruMonthly,
      max_pages_per_file: mineruPerFile,
    },
  };
}

function DefaultQuotaField({
  label,
  value,
  unit,
  suffix,
  rawSuffix,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  unit: number;
  suffix: string;
  rawSuffix: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const raw = parseQuotaInput(value, unit);
  return (
    <label className="block text-xs text-[var(--muted-foreground)]">
      {label}
      <div className="mt-1 flex items-center gap-2">
        <input
          type="number"
          min={0}
          step={unit === 1 ? 1 : 0.1}
          inputMode={unit === 1 ? "numeric" : "decimal"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)] disabled:opacity-50"
        />
        <span className="shrink-0 text-[11px]">{suffix}</span>
      </div>
      <span className="mt-1 block text-[10px]">
        {raw === null
          ? "请输入有效数字"
          : raw === 0
            ? "0 = 不限"
            : `实际 ${formatQuotaRaw(raw, rawSuffix)}`}
      </span>
    </label>
  );
}

// Delegates to the shared locale mapping so a new UI language only has to be
// taught to lib/datetime; the guard here is for the empty or unparseable
// created_at that Intl would throw on.
function formatDate(iso: string, lang: Language): string {
  if (!iso) return "—";
  try {
    return formatLocaleDate(new Date(iso), lang);
  } catch {
    return "—";
  }
}

export default function AdminUsersPage() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const lang: Language = i18n.language?.startsWith("zh") ? "zh" : "en";
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [query, setQuery] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<{
    kind: "delete" | "promote" | "demote";
    user: UserRecord;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [createUsername, setCreateUsername] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createError, setCreateError] = useState("");
  const [defaultQuotaDraft, setDefaultQuotaDraft] = useState<QuotaDraft>(() =>
    quotaToDraft(FALLBACK_DEFAULT_QUOTA),
  );
  const [defaultQuotaLoading, setDefaultQuotaLoading] = useState(true);
  const [defaultQuotaSaving, setDefaultQuotaSaving] = useState(false);
  const [defaultQuotaError, setDefaultQuotaError] = useState("");
  const [defaultQuotaSaved, setDefaultQuotaSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listUsers();
      setUsers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load users"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const loadDefaultQuota = useCallback(async () => {
    setDefaultQuotaLoading(true);
    setDefaultQuotaError("");
    try {
      const quota = await fetchDefaultQuota();
      setDefaultQuotaDraft(quotaToDraft(quota));
    } catch (e) {
      setDefaultQuotaError(
        e instanceof Error ? e.message : t("Failed to load default quota"),
      );
    } finally {
      setDefaultQuotaLoading(false);
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
      setCurrentUser(status.username ?? null);
      void load();
      void loadDefaultQuota();
    });
  }, [router, load, loadDefaultQuota]);

  async function handleDefaultQuotaSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (defaultQuotaSaving) return;
    setDefaultQuotaError("");
    setDefaultQuotaSaved(false);

    const quota = draftToQuota(defaultQuotaDraft);
    if (!quota) {
      setDefaultQuotaError(t("Quota must be a valid number from 0 to 10 billion."));
      return;
    }

    setDefaultQuotaSaving(true);
    try {
      const saved = await saveDefaultQuota(quota);
      setDefaultQuotaDraft(quotaToDraft(saved));
      setDefaultQuotaSaved(true);
    } catch (e) {
      setDefaultQuotaError(
        e instanceof Error ? e.message : t("Failed to save default quota"),
      );
    } finally {
      setDefaultQuotaSaving(false);
    }
  }

  function openCreateDialog() {
    setCreateUsername("");
    setCreatePassword("");
    setCreateError("");
    setShowCreateDialog(true);
  }

  function closeCreateDialog() {
    if (createSubmitting) return;
    setShowCreateDialog(false);
  }

  async function handleCreateSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (createSubmitting) return;
    setCreateError("");
    const username = createUsername.trim();
    if (!username) {
      setCreateError(t("Username is required."));
      return;
    }
    if (createPassword.length < 8) {
      setCreateError(t("Password must be at least 8 characters."));
      return;
    }
    setCreateSubmitting(true);
    try {
      await createUser(username, createPassword);
      setShowCreateDialog(false);
      await load();
    } catch (e) {
      setCreateError(
        e instanceof Error ? e.message : t("Failed to create user"),
      );
    } finally {
      setCreateSubmitting(false);
    }
  }

  async function handleConfirmAction() {
    if (!confirmTarget || confirmBusy) return;
    const { kind, user } = confirmTarget;
    setConfirmBusy(true);
    setActionError("");
    try {
      if (kind === "delete") {
        await deleteUser(user.username);
        setUsers((prev) => prev.filter((u) => u.username !== user.username));
      } else {
        const newRole = kind === "promote" ? "admin" : "user";
        await setUserRole(user.username, newRole);
        setUsers((prev) =>
          prev.map((u) =>
            u.username === user.username ? { ...u, role: newRole } : u,
          ),
        );
        if (newRole === "admin") {
          setExpandedUserId((current) =>
            current === user.id ? null : current,
          );
        }
      }
      setConfirmTarget(null);
    } catch (e) {
      setConfirmTarget(null);
      setActionError(
        e instanceof Error
          ? e.message
          : confirmTarget.kind === "delete"
            ? t("Failed to delete user")
            : t("Failed to update role"),
      );
    } finally {
      setConfirmBusy(false);
    }
  }

  useEffect(() => {
    if (!expandedUserId) return;
    const expanded = users.find((user) => user.id === expandedUserId);
    if (!expanded || expanded.role === "admin") {
      setExpandedUserId(null);
    }
  }, [expandedUserId, users]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredUsers = filterUsersByQuery(users, query);

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="mb-8">
          <Link
            href="/"
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={16} />
            {t("Back")}
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                {t("User Management")}
              </h1>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t("Manage registered accounts")}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Link
                href="/admin/byok"
                className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted-foreground)] transition-colors hover:bg-[var(--card)] hover:text-[var(--foreground)]"
              >
                <KeyRound size={14} />
                BYOK
              </Link>
              <button
                onClick={openCreateDialog}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--foreground)]
                           hover:bg-[var(--card)] transition-colors"
              >
                <UserPlus size={14} />
                {t("Add user")}
              </button>
              <button
                onClick={load}
                disabled={loading}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--muted-foreground)]
                           hover:text-[var(--foreground)] hover:bg-[var(--card)]
                           disabled:opacity-50 transition-colors"
              >
                <RefreshCw
                  size={14}
                  className={loading ? "animate-spin" : ""}
                />
                {t("Refresh")}
              </button>
            </div>
          </div>
        </div>

        {actionError && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {actionError}
          </div>
        )}

        <form
          onSubmit={handleDefaultQuotaSubmit}
          className="mb-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-[var(--foreground)]">
                {t("New-user default quota")}
              </h2>
              <p className="mt-1 max-w-2xl text-xs leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "These limits are snapshotted when a new regular user is created. Existing users keep their current grant.",
                )}
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-[var(--border)]/60 p-3">
              <h3 className="mb-3 text-xs font-semibold text-[var(--foreground)]">
                LLM
              </h3>
              <div className="space-y-3">
                <DefaultQuotaField
                  label="每日额度"
                  value={defaultQuotaDraft.llm.daily}
                  unit={LLM_TOKEN_UNIT}
                  suffix="万 tokens"
                  rawSuffix="tokens"
                  disabled={defaultQuotaLoading || defaultQuotaSaving}
                  onChange={(value) => {
                    setDefaultQuotaDraft((current) => ({
                      ...current,
                      llm: { ...current.llm, daily: value },
                    }));
                    setDefaultQuotaSaved(false);
                  }}
                />
                <DefaultQuotaField
                  label="每月额度"
                  value={defaultQuotaDraft.llm.monthly}
                  unit={LLM_TOKEN_UNIT}
                  suffix="万 tokens"
                  rawSuffix="tokens"
                  disabled={defaultQuotaLoading || defaultQuotaSaving}
                  onChange={(value) => {
                    setDefaultQuotaDraft((current) => ({
                      ...current,
                      llm: { ...current.llm, monthly: value },
                    }));
                    setDefaultQuotaSaved(false);
                  }}
                />
              </div>
            </div>
            <div className="rounded-xl border border-[var(--border)]/60 p-3">
              <h3 className="mb-3 text-xs font-semibold text-[var(--foreground)]">
                Embedding
              </h3>
              <div className="space-y-3">
                <DefaultQuotaField
                  label="每日额度"
                  value={defaultQuotaDraft.embedding.daily}
                  unit={EMBEDDING_TOKEN_UNIT}
                  suffix="百万 tokens"
                  rawSuffix="tokens"
                  disabled={defaultQuotaLoading || defaultQuotaSaving}
                  onChange={(value) => {
                    setDefaultQuotaDraft((current) => ({
                      ...current,
                      embedding: { ...current.embedding, daily: value },
                    }));
                    setDefaultQuotaSaved(false);
                  }}
                />
                <DefaultQuotaField
                  label="每月额度"
                  value={defaultQuotaDraft.embedding.monthly}
                  unit={EMBEDDING_TOKEN_UNIT}
                  suffix="百万 tokens"
                  rawSuffix="tokens"
                  disabled={defaultQuotaLoading || defaultQuotaSaving}
                  onChange={(value) => {
                    setDefaultQuotaDraft((current) => ({
                      ...current,
                      embedding: { ...current.embedding, monthly: value },
                    }));
                    setDefaultQuotaSaved(false);
                  }}
                />
              </div>
            </div>
            <div className="rounded-xl border border-[var(--border)]/60 p-3">
              <h3 className="mb-3 text-xs font-semibold text-[var(--foreground)]">
                MinerU
              </h3>
              <div className="space-y-3">
                <DefaultQuotaField
                  label="每日页数"
                  value={defaultQuotaDraft.mineru.daily}
                  unit={1}
                  suffix="页"
                  rawSuffix="pages"
                  disabled={defaultQuotaLoading || defaultQuotaSaving}
                  onChange={(value) => {
                    setDefaultQuotaDraft((current) => ({
                      ...current,
                      mineru: { ...current.mineru, daily: value },
                    }));
                    setDefaultQuotaSaved(false);
                  }}
                />
                <DefaultQuotaField
                  label="每月页数"
                  value={defaultQuotaDraft.mineru.monthly}
                  unit={1}
                  suffix="页"
                  rawSuffix="pages"
                  disabled={defaultQuotaLoading || defaultQuotaSaving}
                  onChange={(value) => {
                    setDefaultQuotaDraft((current) => ({
                      ...current,
                      mineru: { ...current.mineru, monthly: value },
                    }));
                    setDefaultQuotaSaved(false);
                  }}
                />
                <DefaultQuotaField
                  label="单文件最大页数"
                  value={defaultQuotaDraft.mineru.perFile}
                  unit={1}
                  suffix="页"
                  rawSuffix="pages"
                  disabled={defaultQuotaLoading || defaultQuotaSaving}
                  onChange={(value) => {
                    setDefaultQuotaDraft((current) => ({
                      ...current,
                      mineru: { ...current.mineru, perFile: value },
                    }));
                    setDefaultQuotaSaved(false);
                  }}
                />
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-[var(--muted-foreground)]">
              {t("Set a period to 0 for unlimited usage.")}
            </p>
            <button
              type="submit"
              disabled={
                defaultQuotaLoading ||
                defaultQuotaSaving
              }
              className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-40"
            >
              {defaultQuotaSaving
                ? t("Saving…")
                : defaultQuotaSaved
                  ? t("Saved")
                  : t("Save default quota")}
            </button>
          </div>
          {defaultQuotaError && (
            <p className="mt-3 text-xs text-red-500">{defaultQuotaError}</p>
          )}
        </form>

        {!loading && !error && users.length > 0 && (
          <div className="mb-4 flex items-center gap-3">
            <div className="relative flex-1">
              <Search
                size={14}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("Search users…")}
                aria-label={t("Search users")}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] py-2 pl-9 pr-3 text-sm
                           text-[var(--foreground)] placeholder:text-[var(--muted-foreground)]/70
                           outline-none focus:border-[var(--ring)] transition-colors"
              />
            </div>
            <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
              {normalizedQuery
                ? t("{{filtered}} of {{total}}", {
                    filtered: filteredUsers.length,
                    total: users.length,
                  })
                : t(users.length === 1 ? "{{count}} user" : "{{count}} users", {
                    count: users.length,
                  })}
            </span>
          </div>
        )}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] overflow-hidden shadow-sm">
          {loading ? (
            <div className="divide-y divide-[var(--border)]" aria-hidden>
              {[0, 1, 2].map((row) => (
                <div
                  key={row}
                  className="flex animate-pulse items-center gap-3 px-5 py-4"
                >
                  <div className="h-8 w-8 rounded-full bg-[var(--muted)]/60" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3 w-36 rounded bg-[var(--muted)]/60" />
                    <div className="h-2.5 w-24 rounded bg-[var(--muted)]/40" />
                  </div>
                  <div className="h-5 w-16 rounded-full bg-[var(--muted)]/40" />
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-16 text-red-500 text-sm">
              {error}
            </div>
          ) : users.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <Users
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No users yet")}
              </p>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t("Accounts you create will appear here.")}
              </p>
              <button
                onClick={openCreateDialog}
                className="mt-4 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--foreground)]
                           hover:bg-[var(--background)]/60 transition-colors"
              >
                <UserPlus size={14} />
                {t("Add user")}
              </button>
            </div>
          ) : filteredUsers.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <Search
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No users match “{{query}}”", { query: query.trim() })}
              </p>
              <button
                onClick={() => setQuery("")}
                className="mt-4 rounded-lg px-3 py-1.5 text-sm border border-[var(--border)]
                           text-[var(--muted-foreground)] hover:text-[var(--foreground)]
                           hover:bg-[var(--background)]/60 transition-colors"
              >
                {t("Clear search")}
              </button>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                  <th className="px-5 py-3 font-medium">{t("Username")}</th>
                  <th className="px-5 py-3 font-medium">{t("Role")}</th>
                  <th className="px-5 py-3 font-medium">{t("Joined")}</th>
                  <th className="px-5 py-3 font-medium text-right">
                    {t("Actions")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filteredUsers.map((user) => {
                  const isSelf = user.username === currentUser;
                  const isAdmin = user.role === "admin";
                  const canManageAssignments = !isAdmin && Boolean(user.id);
                  return (
                    <Fragment key={user.username}>
                      <tr className="group hover:bg-[var(--background)]/50 transition-colors">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-3">
                            <UserAvatar
                              username={user.username}
                              userId={user.id}
                              avatar={user.avatar}
                              role={user.role}
                              size={32}
                            />
                            <span className="min-w-0 truncate font-medium text-[var(--foreground)]">
                              {user.username}
                              {isSelf && (
                                <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">
                                  {t("(you)")}
                                </span>
                              )}
                            </span>
                          </div>
                        </td>
                        <td className="px-5 py-3">
                          <span
                            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium
                            ${
                              isAdmin
                                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                                : "bg-[var(--muted)]/50 text-[var(--muted-foreground)]"
                            }`}
                          >
                            {isAdmin && (
                              <ShieldCheck size={11} strokeWidth={2} />
                            )}
                            {isAdmin ? t("Admin") : t("User")}
                          </span>
                        </td>
                        <td className="px-5 py-3.5 text-[var(--muted-foreground)]">
                          {formatDate(user.created_at, lang)}
                        </td>
                        <td className="px-5 py-3.5">
                          <div className="flex items-center justify-end gap-1.5">
                            {canManageAssignments && (
                              <button
                                onClick={() =>
                                  setExpandedUserId((current) =>
                                    current === user.id ? null : user.id,
                                  )
                                }
                                title={t("Manage assignments")}
                                className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                         hover:bg-[var(--background)] hover:text-[var(--foreground)]
                                         transition-colors"
                              >
                                <SlidersHorizontal size={15} />
                              </button>
                            )}
                            <button
                              onClick={() =>
                                setConfirmTarget({
                                  kind: isAdmin ? "demote" : "promote",
                                  user,
                                })
                              }
                              disabled={isSelf}
                              title={
                                isSelf
                                  ? t("Cannot change your own role")
                                  : user.role === "admin"
                                    ? t("Demote to user")
                                    : t("Promote to admin")
                              }
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                       hover:bg-[var(--background)] hover:text-[var(--foreground)]
                                       disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                            >
                              {user.role === "admin" ? (
                                <ShieldOff size={15} />
                              ) : (
                                <Shield size={15} />
                              )}
                            </button>
                            <button
                              onClick={() =>
                                setConfirmTarget({ kind: "delete", user })
                              }
                              disabled={isSelf}
                              title={
                                isSelf
                                  ? t("Cannot delete your own account")
                                  : t("Delete {{username}}", {
                                      username: user.username,
                                    })
                              }
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                       hover:bg-red-500/10 hover:text-red-500
                                       disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </td>
                      </tr>
                      {canManageAssignments && expandedUserId === user.id && (
                        <tr>
                          <td colSpan={4} className="p-0">
                            <GrantEditor key={user.id} userId={user.id} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <p className="mt-8 text-center text-xs text-[var(--muted-foreground)]">
          {t("DeepTutor Admin · User Management")}
        </p>
      </div>

      <ConfirmDialog
        open={confirmTarget !== null}
        title={
          confirmTarget?.kind === "delete"
            ? t("Delete user")
            : confirmTarget?.kind === "promote"
              ? t("Promote to admin")
              : t("Demote to user")
        }
        tone={confirmTarget?.kind === "delete" ? "danger" : "default"}
        confirmLabel={
          confirmTarget?.kind === "delete"
            ? t("Delete user")
            : confirmTarget?.kind === "promote"
              ? t("Promote")
              : t("Demote")
        }
        busyLabel={
          confirmTarget?.kind === "delete"
            ? t("Deleting…")
            : confirmTarget?.kind === "promote"
              ? t("Promoting…")
              : t("Demoting…")
        }
        busy={confirmBusy}
        onConfirm={handleConfirmAction}
        onCancel={() => setConfirmTarget(null)}
      >
        {confirmTarget && (
          <>
            <div className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--background)]/50 px-3 py-2.5">
              <UserAvatar
                username={confirmTarget.user.username}
                userId={confirmTarget.user.id}
                avatar={confirmTarget.user.avatar}
                role={confirmTarget.user.role}
                size={32}
              />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-[var(--foreground)]">
                  {confirmTarget.user.username}
                </p>
                <p className="text-xs text-[var(--muted-foreground)]">
                  {t("{{role}} · joined {{date}}", {
                    role:
                      confirmTarget.user.role === "admin"
                        ? t("Admin")
                        : t("User"),
                    date: formatDate(confirmTarget.user.created_at, lang),
                  })}
                </p>
              </div>
            </div>
            <p className="mt-3">
              {confirmTarget.kind === "delete"
                ? t(
                    "This permanently removes the account and its assignments. This cannot be undone.",
                  )
                : confirmTarget.kind === "promote"
                  ? t(
                      "Admins can manage users and assignments, and work in the shared main workspace.",
                    )
                  : t(
                      "They will lose access to the admin area and switch to their own assigned workspace.",
                    )}
            </p>
          </>
        )}
      </ConfirmDialog>

      {showCreateDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
          role="dialog"
          aria-modal="true"
          onClick={closeCreateDialog}
        >
          <form
            onClick={(e) => e.stopPropagation()}
            onSubmit={handleCreateSubmit}
            className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold text-[var(--foreground)]">
                {t("Add user")}
              </h2>
              <button
                type="button"
                onClick={closeCreateDialog}
                disabled={createSubmitting}
                className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] disabled:opacity-40"
                aria-label={t("Close")}
              >
                <X size={16} />
              </button>
            </div>

            <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
              {t("Username (or email)")}
              <input
                type="text"
                value={createUsername}
                onChange={(e) => setCreateUsername(e.target.value)}
                disabled={createSubmitting}
                autoComplete="off"
                autoFocus
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
            </label>

            <label className="mb-4 block text-xs text-[var(--muted-foreground)]">
              {t("Password (≥ 8 chars)")}
              <input
                type="password"
                value={createPassword}
                onChange={(e) => setCreatePassword(e.target.value)}
                disabled={createSubmitting}
                autoComplete="new-password"
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
            </label>

            {createError && (
              <p className="mb-3 text-xs text-red-500">{createError}</p>
            )}

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeCreateDialog}
                disabled={createSubmitting}
                className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
              >
                {t("Cancel")}
              </button>
              <button
                type="submit"
                disabled={createSubmitting}
                className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-40"
              >
                {createSubmitting ? t("Creating…") : t("Create")}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

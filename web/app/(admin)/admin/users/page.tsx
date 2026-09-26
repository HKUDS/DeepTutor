"use client";

import { Fragment, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import {
  deleteUsers,
  listUsers,
  deleteUser,
  setUserRole,
  createUser,
  importUsers,
  type UserRecord,
  type AccountPreset,
  type UserImportResult,
} from "@/lib/admin-api";
import { GrantEditor } from "@/features/multi-user/components/GrantEditor";
import { BookPermissionEditor } from "@/features/multi-user/components/BookPermissionEditor";
import { LearnerProfileEditor } from "@/features/multi-user/components/LearnerProfileEditor";
import { GuardianRelationshipsEditor } from "@/features/multi-user/components/GuardianRelationshipsEditor";
import { UserAvatar } from "@/components/UserAvatar";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { filterUsersByQuery } from "@/lib/admin-users";
import {
  Search,
  Shield,
  ShieldCheck,
  ShieldOff,
  Trash2,
  RefreshCw,
  ArrowLeft,
  SlidersHorizontal,
  Upload,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { formatDate as formatLocaleDate, type Language } from "@/lib/datetime";

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
  const [showImportDialog, setShowImportDialog] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedUsernames, setSelectedUsernames] = useState<string[]>([]);
  const [showBatchDeleteConfirm, setShowBatchDeleteConfirm] = useState(false);
  const [batchDeleteBusy, setBatchDeleteBusy] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState<{
    kind: "delete" | "promote" | "demote";
    user: UserRecord;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [createUsername, setCreateUsername] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createPreset, setCreatePreset] = useState<AccountPreset>("standard");
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createError, setCreateError] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importSubmitting, setImportSubmitting] = useState(false);
  const [importError, setImportError] = useState("");
  const [importResult, setImportResult] = useState<UserImportResult | null>(null);

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
    });
  }, [router, load]);

  function openCreateDialog() {
    setCreateUsername("");
    setCreatePassword("");
    setCreatePreset("standard");
    setCreateError("");
    setShowCreateDialog(true);
  }

  function openImportDialog() {
    setImportFile(null);
    setImportError("");
    setImportResult(null);
    setImportSubmitting(false);
    setShowImportDialog(true);
  }

  function closeImportDialog() {
    if (importSubmitting) return;
    setShowImportDialog(false);
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
      await createUser(username, createPassword, createPreset);
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

  async function handleImportSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (importSubmitting) return;
    if (!importFile) {
      setImportError(t("Select a CSV file."));
      return;
    }
    setImportSubmitting(true);
    setImportError("");
    try {
      const result = await importUsers(importFile);
      setImportResult(result);
      await load();
    } catch (e) {
      setImportError(
        e instanceof Error ? e.message : t("Failed to import users"),
      );
    } finally {
      setImportSubmitting(false);
    }
  }

  function toggleSelectedUsername(username: string) {
    setSelectedUsernames((current) =>
      current.includes(username)
        ? current.filter((item) => item !== username)
        : [...current, username],
    );
  }

  async function handleBatchDeleteConfirm() {
    if (batchDeleteBusy || selectedUsernames.length === 0) return;
    setBatchDeleteBusy(true);
    setActionError("");
    try {
      const result = await deleteUsers(selectedUsernames);
      const failed = new Set(
        result.results
          .filter((item) => !item.ok)
          .map((item) => item.username),
      );
      setSelectedUsernames((current) =>
        current.filter((username) => failed.has(username)),
      );
      setShowBatchDeleteConfirm(false);
      await load();
      if (failed.size > 0) {
        setActionError(
          t("{{count}} users could not be deleted: {{users}}", {
            count: failed.size,
            users: [...failed].join(", "),
          }),
        );
      }
    } catch (e) {
      setShowBatchDeleteConfirm(false);
      setActionError(
        e instanceof Error ? e.message : t("Failed to delete users"),
      );
    } finally {
      setBatchDeleteBusy(false);
    }
  }

  useEffect(() => {
    if (!expandedUserId) return;
    const expanded = users.find((user) => user.id === expandedUserId);
    if (!expanded || expanded.role === "admin") {
      setExpandedUserId(null);
    }
  }, [expandedUserId, users]);

  useEffect(() => {
    if (selectedUsernames.length === 0) return;
    const usernames = new Set(users.map((user) => user.username));
    setSelectedUsernames((current) => {
      const retained = current.filter((username) => usernames.has(username));
      return retained.length === current.length ? current : retained;
    });
  }, [users, selectedUsernames]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredUsers = filterUsersByQuery(users, query);
  const selectableFilteredUsers = filteredUsers.filter(
    (user) => user.username !== currentUser,
  );
  const selectedUsernameSet = new Set(selectedUsernames);
  const allFilteredSelected =
    selectableFilteredUsers.length > 0 &&
    selectableFilteredUsers.every((user) =>
      selectedUsernameSet.has(user.username),
    );

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
                onClick={openImportDialog}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--foreground)]
                           hover:bg-[var(--card)] transition-colors"
              >
                <Upload size={14} />
                {t("Import users")}
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

        {!loading && !error && selectedUsernames.length > 0 && (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-3">
            <span className="text-sm text-[var(--muted-foreground)]">
              {t("{{count}} users selected", { count: selectedUsernames.length })}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSelectedUsernames([])}
                className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
              >
                {t("Clear selection")}
              </button>
              <button
                onClick={() => setShowBatchDeleteConfirm(true)}
                className="flex items-center gap-1.5 rounded-lg border border-red-500/40 px-3 py-1.5 text-sm text-red-600 hover:bg-red-500/10 transition-colors dark:text-red-400"
              >
                <Trash2 size={14} />
                {t("Delete selected")}
              </button>
            </div>
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
                  <th className="w-12 px-5 py-3">
                    <input
                      type="checkbox"
                      checked={allFilteredSelected}
                      disabled={selectableFilteredUsers.length === 0}
                      onChange={() => {
                        const displayed = new Set(
                          selectableFilteredUsers.map((user) => user.username),
                        );
                        setSelectedUsernames((current) =>
                          allFilteredSelected
                            ? current.filter((username) => !displayed.has(username))
                            : [
                                ...current,
                                ...selectableFilteredUsers
                                  .map((user) => user.username)
                                  .filter((username) => !current.includes(username)),
                              ],
                        );
                      }}
                      aria-label={t("Select displayed users")}
                      className="h-4 w-4 rounded border-[var(--border)] accent-[var(--foreground)]"
                    />
                  </th>
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
                        <td className="px-5 py-3.5">
                          <input
                            type="checkbox"
                            checked={selectedUsernameSet.has(user.username)}
                            disabled={isSelf}
                            onChange={() => toggleSelectedUsername(user.username)}
                            aria-label={t("Select {{username}}", {
                              username: user.username,
                            })}
                            className="h-4 w-4 rounded border-[var(--border)] accent-[var(--foreground)] disabled:opacity-30"
                          />
                        </td>
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
                          {!isAdmin && user.preset && (
                            <span className="mt-1 block text-[11px] text-[var(--muted-foreground)]">
                              {t("Preset: {{preset}}", {
                                preset: t(
                                  user.preset === "learner"
                                    ? "Learner"
                                    : user.preset === "custom"
                                      ? "Custom"
                                      : "Standard",
                                ),
                              })}
                            </span>
                          )}
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
                          <td colSpan={5} className="p-0">
                            <GrantEditor
                              key={user.id}
                              userId={user.id}
                              lockLearningPolicy={user.preset === "learner"}
                            />
                            <BookPermissionEditor userId={user.id} />
                            {user.preset === "learner" && (
                              <>
                                <GuardianRelationshipsEditor
                                  learnerId={user.id}
                                  learnerUsername={user.username}
                                  users={users}
                                />
                                <LearnerProfileEditor
                                  username={user.username}
                                />
                              </>
                            )}
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

      <ConfirmDialog
        open={showBatchDeleteConfirm}
        title={t("Delete users")}
        tone="danger"
        confirmLabel={t("Delete users")}
        busyLabel={t("Deleting…")}
        busy={batchDeleteBusy}
        onConfirm={handleBatchDeleteConfirm}
        onCancel={() => setShowBatchDeleteConfirm(false)}
      >
        <p>
          {t(
            "This permanently removes {{count}} accounts and their assignments. This cannot be undone.",
            { count: selectedUsernames.length },
          )}
        </p>
        <ul className="mt-3 max-h-40 space-y-1 overflow-y-auto text-sm text-[var(--muted-foreground)]">
          {selectedUsernames.map((username) => (
            <li key={username} className="truncate">
              {username}
            </li>
          ))}
        </ul>
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

            <fieldset className="mb-4">
              <legend className="mb-1.5 block text-xs text-[var(--muted-foreground)]">
                {t("Account preset")}
              </legend>
              <div
                className="grid grid-cols-3 gap-1 rounded-lg bg-[var(--muted)]/50 p-1"
                role="group"
                aria-label={t("Account preset")}
              >
                {(["standard", "learner", "custom"] as const).map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    disabled={createSubmitting}
                    aria-pressed={createPreset === preset}
                    onClick={() => setCreatePreset(preset)}
                    className={`rounded-md px-2 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
                      createPreset === preset
                        ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                        : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {t(
                      preset === "learner"
                        ? "Learner"
                        : preset === "custom"
                          ? "Custom"
                          : "Standard",
                    )}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                {createPreset === "learner"
                  ? t(
                      "Chat and Immersive Reading only, with uploads and tools disabled until assigned.",
                    )
                  : createPreset === "custom"
                    ? t(
                        "Create an ordinary account, then customize its assignments.",
                      )
                    : t(
                        "Create an ordinary account with the default workspace behavior.",
                      )}
              </p>
            </fieldset>

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

      {showImportDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
          role="dialog"
          aria-modal="true"
          onClick={closeImportDialog}
        >
          <form
            onClick={(e) => e.stopPropagation()}
            onSubmit={handleImportSubmit}
            className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold text-[var(--foreground)]">
                {t("Import users")}
              </h2>
              <button
                type="button"
                onClick={closeImportDialog}
                disabled={importSubmitting}
                className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] disabled:opacity-40"
                aria-label={t("Close")}
              >
                <X size={16} />
              </button>
            </div>

            <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
              {t("CSV file")}
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => {
                  setImportFile(e.target.files?.[0] ?? null);
                  setImportResult(null);
                  setImportError("");
                }}
                disabled={importSubmitting}
                autoFocus
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
            </label>

            <p className="mb-3 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {t("Header: username,password,preset. Only ordinary user accounts can be imported.")}
            </p>

            {importError && (
              <p className="mb-3 text-xs text-red-500">{importError}</p>
            )}

            {importResult && (
              <div className="mb-4">
                <p className="text-sm font-medium text-[var(--foreground)]">
                  {t("{{created}} created, {{failed}} failed", {
                    created: importResult.created_count,
                    failed: importResult.failed_count,
                  })}
                </p>
                <ul className="mt-2 max-h-44 space-y-1 overflow-y-auto text-xs text-[var(--muted-foreground)]">
                  {importResult.results.map((result) => (
                    <li
                      key={`${result.row}-${result.username}`}
                      className="flex items-start justify-between gap-3"
                    >
                      <span className="min-w-0 truncate">
                        {t("Row {{row}}", { row: result.row })} · {result.username}
                      </span>
                      <span
                        className={
                          result.ok
                            ? "shrink-0 text-emerald-600 dark:text-emerald-400"
                            : "shrink-0 text-red-500"
                        }
                      >
                        {result.ok ? t("Created") : result.error}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeImportDialog}
                disabled={importSubmitting}
                className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
              >
                {t("Close")}
              </button>
              <button
                type="submit"
                disabled={importSubmitting || !importFile}
                className="flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-40"
              >
                <Upload size={14} />
                {importSubmitting ? t("Importing…") : t("Import")}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

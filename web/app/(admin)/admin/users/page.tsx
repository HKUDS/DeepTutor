"use client";

import { Fragment, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { fetchAuthStatus } from "@/lib/auth";
import {
  listUsers,
  deleteUser,
  setUserRole,
  createUser,
  type UserRecord,
} from "@/lib/admin-api";
import { GrantEditor } from "@/features/multi-user/components/GrantEditor";
import {
  Shield,
  ShieldOff,
  Trash2,
  RefreshCw,
  ArrowLeft,
  SlidersHorizontal,
  UserPlus,
  X,
} from "lucide-react";
import Link from "next/link";

function formatDate(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return "—";
  }
}

export default function AdminUsersPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [createUsername, setCreateUsername] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listUsers();
      setUsers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

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
      setCreateError("Username is required.");
      return;
    }
    if (createPassword.length < 8) {
      setCreateError("Password must be at least 8 characters.");
      return;
    }
    setCreateSubmitting(true);
    try {
      await createUser(username, createPassword);
      setShowCreateDialog(false);
      await load();
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Failed to create user");
    } finally {
      setCreateSubmitting(false);
    }
  }

  async function handleDelete(username: string) {
    if (!window.confirm(`Delete user "${username}"? This cannot be undone.`))
      return;
    setActionError("");
    try {
      await deleteUser(username);
      setUsers((prev) => prev.filter((u) => u.username !== username));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to delete user");
    }
  }

  async function handleToggleRole(user: UserRecord) {
    const newRole = user.role === "admin" ? "user" : "admin";
    const verb = newRole === "admin" ? "Promote" : "Demote";
    if (!window.confirm(`${verb} "${user.username}" to ${newRole}?`)) return;
    setActionError("");
    try {
      await setUserRole(user.username, newRole);
      setUsers((prev) =>
        prev.map((u) =>
          u.username === user.username ? { ...u, role: newRole } : u,
        ),
      );
      if (newRole === "admin") {
        setExpandedUserId((current) => (current === user.id ? null : current));
      }
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to update role");
    }
  }

  useEffect(() => {
    if (!expandedUserId) return;
    const expanded = users.find((user) => user.id === expandedUserId);
    if (!expanded || expanded.role === "admin") {
      setExpandedUserId(null);
    }
  }, [expandedUserId, users]);

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="mb-8 flex items-center gap-4">
          <Link
            href="/"
            className="flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={15} />
            Back
          </Link>
          <div className="flex-1">
            <h1 className="text-xl font-semibold text-[var(--foreground)]">
              User Management
            </h1>
            <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
              Manage registered accounts
            </p>
          </div>
          <button
            onClick={openCreateDialog}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                       border border-[var(--border)] text-[var(--foreground)]
                       hover:bg-[var(--card)] transition-colors"
          >
            <UserPlus size={14} />
            Add user
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                       border border-[var(--border)] text-[var(--muted-foreground)]
                       hover:text-[var(--foreground)] hover:bg-[var(--card)]
                       disabled:opacity-50 transition-colors"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>

        {actionError && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {actionError}
          </div>
        )}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] overflow-hidden shadow-sm">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-[var(--muted-foreground)] text-sm">
              Loading…
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-16 text-red-500 text-sm">
              {error}
            </div>
          ) : users.length === 0 ? (
            <div className="flex items-center justify-center py-16 text-[var(--muted-foreground)] text-sm">
              No users found.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                  <th className="px-5 py-3 font-medium">Username</th>
                  <th className="px-5 py-3 font-medium">Role</th>
                  <th className="px-5 py-3 font-medium">Joined</th>
                  <th className="px-5 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {users.map((user) => {
                  const isSelf = user.username === currentUser;
                  const isAdmin = user.role === "admin";
                  const canManageAssignments = !isAdmin && Boolean(user.id);
                  return (
                    <Fragment key={user.username}>
                    <tr
                      className="group hover:bg-[var(--background)]/50 transition-colors"
                    >
                      <td className="px-5 py-3.5 font-medium text-[var(--foreground)]">
                        {user.username}
                        {isSelf && (
                          <span className="ml-2 text-xs text-[var(--muted-foreground)]">
                            (you)
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3.5">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium
                            ${
                              user.role === "admin"
                                ? "bg-purple-500/15 text-purple-600 dark:text-purple-400"
                                : "bg-[var(--muted)]/50 text-[var(--muted-foreground)]"
                            }`}
                        >
                          {user.role === "admin" ? <Shield size={11} /> : null}
                          {user.role}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-[var(--muted-foreground)]">
                        {formatDate(user.created_at)}
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
                              title="Manage assignments"
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)]
                                         hover:bg-[var(--background)] hover:text-[var(--foreground)]
                                         transition-colors"
                            >
                              <SlidersHorizontal size={15} />
                            </button>
                          )}
                          <button
                            onClick={() => handleToggleRole(user)}
                            disabled={isSelf}
                            title={
                              isSelf
                                ? "Cannot change your own role"
                                : user.role === "admin"
                                  ? "Demote to user"
                                  : "Promote to admin"
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
                            onClick={() => handleDelete(user.username)}
                            disabled={isSelf}
                            title={
                              isSelf
                                ? "Cannot delete your own account"
                                : `Delete ${user.username}`
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
                          <GrantEditor userId={user.id} />
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
          DeepTutor Admin · User Management
        </p>
      </div>

      {showCreateDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
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
                Add user
              </h2>
              <button
                type="button"
                onClick={closeCreateDialog}
                disabled={createSubmitting}
                className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)] disabled:opacity-40"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>

            <label className="mb-3 block text-xs text-[var(--muted-foreground)]">
              Username (or email)
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
              Password (≥ 8 chars)
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
                Cancel
              </button>
              <button
                type="submit"
                disabled={createSubmitting}
                className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-40"
              >
                {createSubmitting ? "Creating…" : "Create"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

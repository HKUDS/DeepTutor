"use client";

import { useEffect, useMemo, useState } from "react";
import { KeyRound, ShieldCheck, ShieldOff, UserPlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import type { UserRecord } from "@/lib/admin-api";
import {
  authorizeGuardianRelationship,
  getGuardianReport,
  listAdminGuardianRelationships,
  resetLearnerCredentials,
  revokeGuardianRelationship,
  type GuardianRelationship,
  type GuardianReport,
} from "@/lib/guardian-api";

const PERMISSIONS = [
  "assign_materials",
  "manage_restrictions",
  "view_reports",
  "reset_credentials",
] as const;

const permissionLabels: Record<(typeof PERMISSIONS)[number], string> = {
  assign_materials: "Manage materials",
  manage_restrictions: "Manage restrictions",
  view_reports: "View reports",
  reset_credentials: "Reset credentials",
};

export function GuardianRelationshipsEditor({
  learnerId,
  learnerUsername,
  users,
}: {
  learnerId: string;
  learnerUsername: string;
  users: UserRecord[];
}) {
  const { t } = useTranslation();
  const [relationships, setRelationships] = useState<GuardianRelationship[]>(
    [],
  );
  const [report, setReport] = useState<GuardianReport | null>(null);
  const [guardianId, setGuardianId] = useState("");
  const [permissions, setPermissions] = useState<string[]>([...PERMISSIONS]);
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [confirm, setConfirm] = useState<
    | { kind: "revoke"; relationship: GuardianRelationship }
    | { kind: "reset" }
    | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listAdminGuardianRelationships(),
      getGuardianReport(learnerId),
    ])
      .then(([allRelationships, nextReport]) => {
        if (cancelled) return;
        setRelationships(
          allRelationships.filter(
            (relationship) => relationship.learner_user_id === learnerId,
          ),
        );
        setReport(nextReport);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError((reason as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [learnerId]);

  const activeGuardianIds = useMemo(
    () => new Set(relationships.map((item) => item.guardian_user_id)),
    [relationships],
  );
  const candidates = users.filter(
    (user) =>
      user.role === "user" &&
      user.id !== learnerId &&
      user.preset !== "learner" &&
      !activeGuardianIds.has(user.id),
  );

  const addRelationship = async () => {
    if (!guardianId || permissions.length === 0) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const relationship = await authorizeGuardianRelationship(
        guardianId,
        learnerId,
        permissions,
      );
      setRelationships((current) => [...current, relationship]);
      setGuardianId("");
      setMessage(t("Guardian relationship added."));
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (relationship: GuardianRelationship) => {
    setConfirm(null);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await revokeGuardianRelationship(relationship.id);
      setRelationships((current) =>
        current.filter((item) => item.id !== relationship.id),
      );
      setMessage(t("Guardian access revoked."));
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const resetCredentials = async () => {
    if (newPassword.length < 8) return;
    setConfirm(null);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await resetLearnerCredentials(learnerId, newPassword);
      setNewPassword("");
      setMessage(t("Learner credentials were reset."));
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="border-t border-[var(--border)] bg-[var(--background)]/40 px-5 py-4">
      <div className="mb-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--foreground)]">
          <ShieldCheck className="h-4 w-4" /> {t("Guardian relationships")}
        </h3>
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          {t("Authorize ordinary accounts to supervise {{username}}.", {
            username: learnerUsername,
          })}
        </p>
      </div>

      {loading ? (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t("Loading guardian relationships…")}
        </p>
      ) : (
        <>
          <div className="mb-3 grid gap-2">
            {relationships.length === 0 ? (
              <p className="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted-foreground)]">
                {t("No active guardian relationships.")}
              </p>
            ) : (
              relationships.map((relationship) => (
                <div
                  key={relationship.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="truncate text-xs font-medium">
                      {relationship.guardian_username}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                      {relationship.permissions
                        .map((permission) =>
                          t(
                            permissionLabels[
                              permission as (typeof PERMISSIONS)[number]
                            ] ?? permission,
                          ),
                        )
                        .join(" · ")}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setConfirm({ kind: "revoke", relationship })}
                    className="rounded-md p-1.5 text-red-600 hover:bg-red-500/10 disabled:opacity-40"
                    aria-label={t("Revoke access")}
                  >
                    <ShieldOff className="h-4 w-4" />
                  </button>
                </div>
              ))
            )}
          </div>

          <div className="rounded-lg border border-[var(--border)] p-3">
            <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
              <select
                value={guardianId}
                disabled={busy || candidates.length === 0}
                onChange={(event) => setGuardianId(event.target.value)}
                className="h-9 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 text-xs"
              >
                <option value="">{t("Select a guardian")}</option>
                {candidates.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.username}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={busy || !guardianId || permissions.length === 0}
                onClick={() => void addRelationship()}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-[var(--primary)] px-3 text-xs text-[var(--primary-foreground)] disabled:opacity-40"
              >
                <UserPlus className="h-3.5 w-3.5" /> {t("Authorize guardian")}
              </button>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {PERMISSIONS.map((permission) => (
                <label
                  key={permission}
                  className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]"
                >
                  <input
                    type="checkbox"
                    checked={permissions.includes(permission)}
                    disabled={busy}
                    onChange={() =>
                      setPermissions((current) =>
                        current.includes(permission)
                          ? current.filter((item) => item !== permission)
                          : [...current, permission],
                      )
                    }
                  />
                  {t(permissionLabels[permission])}
                </label>
              ))}
            </div>
          </div>

          {report && (
            <p className="mt-3 text-xs text-[var(--muted-foreground)]">
              {t(
                "{{materials}} approved materials · {{resources}} enabled resources",
                {
                  materials: report.assigned_materials.length,
                  resources:
                    report.grant_summary.model_count +
                    report.grant_summary.knowledge_base_count +
                    report.grant_summary.skill_count,
                },
              )}
            </p>
          )}

          <div className="mt-3 rounded-lg border border-[var(--border)] p-3">
            <label className="text-xs">
              <span className="mb-1 block text-[var(--muted-foreground)]">
                {t("New learner password")}
              </span>
              <input
                type="password"
                value={newPassword}
                minLength={8}
                autoComplete="new-password"
                disabled={busy}
                onChange={(event) => setNewPassword(event.target.value)}
                className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-3"
              />
            </label>
            <button
              type="button"
              disabled={busy || newPassword.length < 8}
              onClick={() => setConfirm({ kind: "reset" })}
              className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-red-500/40 px-3 py-1.5 text-xs text-red-600 disabled:opacity-40"
            >
              <KeyRound className="h-3.5 w-3.5" />
              {t("Reset learner credentials")}
            </button>
          </div>
        </>
      )}

      {error ? <p className="mt-3 text-xs text-red-600">{error}</p> : null}
      {message ? (
        <p className="mt-3 text-xs text-emerald-600">{message}</p>
      ) : null}

      <ConfirmDialog
        open={confirm !== null}
        title={
          confirm?.kind === "reset"
            ? t("Reset learner credentials")
            : t("Revoke guardian access")
        }
        confirmLabel={
          confirm?.kind === "reset"
            ? t("Reset credentials")
            : t("Revoke access")
        }
        tone="danger"
        busy={busy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.kind === "reset") void resetCredentials();
          if (confirm?.kind === "revoke") void revoke(confirm.relationship);
        }}
      >
        {confirm?.kind === "reset"
          ? t(
              "This changes the learner password and revokes every learner device credential.",
            )
          : t("This immediately removes access to this learner account.")}
      </ConfirmDialog>
    </section>
  );
}

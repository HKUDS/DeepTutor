"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, Trash2, UserPlus, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  createGroupMember,
  getGroupGrantable,
  getGroupMemberGrants,
  getGroupReport,
  listGroups,
  removeGroupMember,
  resetGroupMemberPassword,
  setGroupMemberGrants,
  type GrantableResources,
  type Group,
  type GroupMemberGrant,
  type GroupReportEntry,
} from "@/lib/group-api";

const inputClass =
  "w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)]";
const buttonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--foreground)] transition-colors hover:bg-[var(--background)]/60 disabled:opacity-50";
const primaryButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-sm font-medium text-[var(--primary-foreground)] transition-opacity disabled:opacity-50";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Roster screen for a group lead.
 *
 * Everything here is authorised server-side against `group.lead_user_id`; the
 * client never sends a role, and the report deliberately carries status only —
 * no conversation content ever reaches this page.
 */
export default function GroupsPage() {
  const { t } = useTranslation();

  const [groups, setGroups] = useState<Group[]>([]);
  const [activeId, setActiveId] = useState("");
  const [group, setGroup] = useState<Group | null>(null);
  const [report, setReport] = useState<GroupReportEntry[]>([]);
  const [grantable, setGrantable] = useState<GrantableResources | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const [passwordTarget, setPasswordTarget] = useState<string | null>(null);
  const [passwordValue, setPasswordValue] = useState("");

  const [editingUser, setEditingUser] = useState<string | null>(null);
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [kbs, setKbs] = useState<string[]>([]);
  const [skills, setSkills] = useState<string[]>([]);

  const loadGroup = useCallback(async (groupId: string) => {
    const [body, catalog] = await Promise.all([
      getGroupReport(groupId),
      getGroupGrantable(groupId),
    ]);
    setGroup(body.group);
    setReport(body.members);
    setGrantable(catalog);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const list = await listGroups();
        if (cancelled) return;
        setGroups(list);
        if (list.length > 0) {
          setActiveId(list[0].id);
          await loadGroup(list[0].id);
        }
      } catch (err) {
        if (!cancelled) setError(messageOf(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [loadGroup]);

  const selectGroup = useCallback(
    async (groupId: string) => {
      setActiveId(groupId);
      setEditingUser(null);
      setPasswordTarget(null);
      setError("");
      setNotice("");
      try {
        await loadGroup(groupId);
      } catch (err) {
        setError(messageOf(err));
      }
    },
    [loadGroup],
  );

  const addMember = useCallback(async () => {
    if (!group) return;
    setBusy("add");
    setError("");
    setNotice("");
    try {
      await createGroupMember(group.id, newUsername.trim(), newPassword);
      setNewUsername("");
      setNewPassword("");
      await loadGroup(group.id);
      setNotice(t("Member added."));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }, [group, loadGroup, newPassword, newUsername, t]);

  const removeMember = useCallback(
    async (username: string) => {
      if (!group) return;
      setBusy(`remove:${username}`);
      setError("");
      setNotice("");
      try {
        await removeGroupMember(group.id, username);
        if (editingUser === username) setEditingUser(null);
        await loadGroup(group.id);
        setNotice(t("Member removed."));
      } catch (err) {
        setError(messageOf(err));
      } finally {
        setBusy("");
      }
    },
    [editingUser, group, loadGroup, t],
  );

  const submitPassword = useCallback(async () => {
    if (!group || !passwordTarget) return;
    setBusy(`password:${passwordTarget}`);
    setError("");
    setNotice("");
    try {
      await resetGroupMemberPassword(group.id, passwordTarget, passwordValue);
      setPasswordTarget(null);
      setPasswordValue("");
      setNotice(t("Password reset."));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }, [group, passwordTarget, passwordValue, t]);

  const openGrants = useCallback(
    async (username: string) => {
      if (!group) return;
      setEditingUser(username);
      setError("");
      setNotice("");
      try {
        const current = await getGroupMemberGrants(group.id, username);
        const nextModels: Record<string, string[]> = {};
        for (const item of current.models) {
          nextModels[item.profile_id] = item.model_ids ?? [];
        }
        setModels(nextModels);
        setKbs(
          current.knowledge_bases
            .map((item) => item.name ?? item.kb_name ?? "")
            .filter(Boolean),
        );
        setSkills(
          current.skills.map((item) => item.skill_id ?? item.id ?? "").filter(Boolean),
        );
      } catch (err) {
        setError(messageOf(err));
      }
    },
    [group],
  );

  const toggleModel = useCallback((profileId: string, modelId: string) => {
    setModels((previous) => {
      const current = previous[profileId] ?? [];
      const next = current.includes(modelId)
        ? current.filter((item) => item !== modelId)
        : [...current, modelId];
      return { ...previous, [profileId]: next };
    });
  }, []);

  const saveGrants = useCallback(async () => {
    if (!group || !editingUser) return;
    setBusy(`grants:${editingUser}`);
    setError("");
    setNotice("");
    const payload: GroupMemberGrant = {
      models: Object.entries(models)
        .filter(([, ids]) => ids.length > 0)
        .map(([profile_id, model_ids]) => ({ profile_id, model_ids })),
      knowledge_bases: kbs.map((name) => ({ name })),
      skills: skills.map((skill_id) => ({ skill_id })),
    };
    try {
      await setGroupMemberGrants(group.id, editingUser, payload);
      setEditingUser(null);
      await loadGroup(group.id);
      setNotice(t("Access updated."));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy("");
    }
  }, [editingUser, group, kbs, loadGroup, models, skills, t]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--background)] px-4 py-10">
        <p className="mx-auto max-w-4xl text-sm text-[var(--muted-foreground)]">
          {t("Loading…")}
        </p>
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className="min-h-screen bg-[var(--background)] px-4 py-10">
        <div className="mx-auto max-w-4xl rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
          <div className="flex items-center gap-2.5">
            <Users size={18} className="text-[var(--primary)]" />
            <h1 className="text-lg font-semibold text-[var(--foreground)]">
              {t("Teams")}
            </h1>
          </div>
          <p className="mt-3 text-sm text-[var(--muted-foreground)]">
            {t("You do not lead any team.")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--background)] px-4 py-10">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Users size={18} className="text-[var(--primary)]" />
            <h1 className="text-lg font-semibold text-[var(--foreground)]">
              {t("Teams")}
            </h1>
          </div>
          {groups.length > 1 && (
            <select
              value={activeId}
              onChange={(event) => void selectGroup(event.target.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--foreground)]"
              aria-label={t("Team")}
            >
              {groups.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {error && (
          <p className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        {notice && (
          <p className="rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-400">
            {notice}
          </p>
        )}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
          <h2 className="text-sm font-medium text-[var(--foreground)]">
            {group?.name} · {t("Team members")}
          </h2>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-[var(--muted-foreground)]">
                <tr>
                  <th className="py-2 pr-3 font-medium">{t("Username")}</th>
                  <th className="py-2 pr-3 font-medium">{t("Status")}</th>
                  <th className="py-2 pr-3 font-medium">{t("Last active")}</th>
                  <th className="py-2 pr-3 font-medium">{t("Access")}</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {report.map((entry) => {
                  const isLead = entry.user_id === group?.lead_user_id;
                  return (
                    <tr key={entry.user_id} className="border-t border-[var(--border)]">
                      <td className="py-2.5 pr-3 text-[var(--foreground)]">
                        {entry.username}
                        {isLead && (
                          <span className="ml-2 rounded bg-[var(--primary)]/10 px-1.5 py-0.5 text-[11px] text-[var(--primary)]">
                            {t("Lead")}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 text-[var(--muted-foreground)]">
                        {entry.disabled
                          ? t("Disabled")
                          : entry.must_change_password
                            ? t("Must change password")
                            : t("Active")}
                      </td>
                      <td className="py-2.5 pr-3 text-[var(--muted-foreground)]">
                        {entry.last_active_at
                          ? new Date(entry.last_active_at).toLocaleString()
                          : t("Never active")}
                      </td>
                      <td className="py-2.5 pr-3 text-[var(--muted-foreground)]">
                        {t("{{models}} models · {{kbs}} knowledge bases · {{skills}} skills", {
                          models: entry.grant_summary.model_count,
                          kbs: entry.grant_summary.knowledge_base_count,
                          skills: entry.grant_summary.skill_count,
                        })}
                      </td>
                      <td className="py-2.5">
                        {!isLead && (
                          <div className="flex flex-wrap justify-end gap-1.5">
                            <button
                              type="button"
                              className={buttonClass}
                              onClick={() => void openGrants(entry.username)}
                            >
                              {t("Edit access")}
                            </button>
                            <button
                              type="button"
                              className={buttonClass}
                              onClick={() => {
                                setPasswordTarget(entry.username);
                                setPasswordValue("");
                              }}
                            >
                              <KeyRound size={14} />
                              {t("Reset password")}
                            </button>
                            <button
                              type="button"
                              className={buttonClass}
                              disabled={busy === `remove:${entry.username}`}
                              onClick={() => void removeMember(entry.username)}
                            >
                              <Trash2 size={14} />
                              {t("Remove")}
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-[var(--muted-foreground)]">
            {t("Removing someone detaches them from the team. The account is kept.")}
          </p>
        </div>

        {passwordTarget && (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
            <h2 className="text-sm font-medium text-[var(--foreground)]">
              {t("Reset password")} · {passwordTarget}
            </h2>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <input
                type="password"
                value={passwordValue}
                onChange={(event) => setPasswordValue(event.target.value)}
                placeholder={t("New password")}
                className={inputClass}
              />
              <button
                type="button"
                className={primaryButtonClass}
                disabled={passwordValue.length < 8 || busy === `password:${passwordTarget}`}
                onClick={() => void submitPassword()}
              >
                {t("Save")}
              </button>
              <button type="button" className={buttonClass} onClick={() => setPasswordTarget(null)}>
                {t("Cancel")}
              </button>
            </div>
          </div>
        )}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
          <h2 className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
            <UserPlus size={16} />
            {t("Add member")}
          </h2>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <input
              value={newUsername}
              onChange={(event) => setNewUsername(event.target.value)}
              placeholder={t("Username")}
              className={inputClass}
            />
            <input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder={t("Initial password")}
              className={inputClass}
            />
            <button
              type="button"
              className={primaryButtonClass}
              disabled={
                busy === "add" || newUsername.trim().length < 2 || newPassword.length < 8
              }
              onClick={() => void addMember()}
            >
              {t("Add")}
            </button>
          </div>
          <p className="mt-3 text-xs text-[var(--muted-foreground)]">
            {t("New members are ordinary accounts and are asked to change the password.")}
          </p>
        </div>

        {editingUser && grantable && (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
            <h2 className="text-sm font-medium text-[var(--foreground)]">
              {t("Access")} · {editingUser}
            </h2>

            <div className="mt-4 space-y-4">
              <div>
                <h3 className="text-xs font-medium text-[var(--muted-foreground)]">
                  {t("Models")}
                </h3>
                {grantable.models.length === 0 && (
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">{t("None")}</p>
                )}
                {grantable.models.map((profile) => (
                  <div key={profile.profile_id} className="mt-2">
                    <p className="text-xs text-[var(--foreground)]">
                      {profile.name || profile.profile_id}
                    </p>
                    <div className="mt-1 flex flex-wrap gap-3">
                      {profile.model_ids.map((modelId) => (
                        <label
                          key={`${profile.profile_id}:${modelId}`}
                          className="flex items-center gap-1.5 text-xs text-[var(--foreground)]"
                        >
                          <input
                            type="checkbox"
                            checked={(models[profile.profile_id] ?? []).includes(modelId)}
                            onChange={() => toggleModel(profile.profile_id, modelId)}
                          />
                          {modelId}
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <h3 className="text-xs font-medium text-[var(--muted-foreground)]">
                  {t("Knowledge bases")}
                </h3>
                <div className="mt-1 flex flex-wrap gap-3">
                  {grantable.knowledge_bases.length === 0 && (
                    <p className="text-xs text-[var(--muted-foreground)]">{t("None")}</p>
                  )}
                  {grantable.knowledge_bases.map((item) => {
                    const name = item.name ?? item.kb_name ?? item.resource_id ?? item.id ?? "";
                    if (!name) return null;
                    return (
                      <label
                        key={name}
                        className="flex items-center gap-1.5 text-xs text-[var(--foreground)]"
                      >
                        <input
                          type="checkbox"
                          checked={kbs.includes(name)}
                          onChange={() =>
                            setKbs((previous) =>
                              previous.includes(name)
                                ? previous.filter((entry) => entry !== name)
                                : [...previous, name],
                            )
                          }
                        />
                        {name}
                      </label>
                    );
                  })}
                </div>
              </div>

              <div>
                <h3 className="text-xs font-medium text-[var(--muted-foreground)]">
                  {t("Skills")}
                </h3>
                <div className="mt-1 flex flex-wrap gap-3">
                  {grantable.skills.length === 0 && (
                    <p className="text-xs text-[var(--muted-foreground)]">{t("None")}</p>
                  )}
                  {grantable.skills.map((item) => {
                    const skillId = item.skill_id ?? item.id ?? "";
                    if (!skillId) return null;
                    return (
                      <label
                        key={skillId}
                        className="flex items-center gap-1.5 text-xs text-[var(--foreground)]"
                      >
                        <input
                          type="checkbox"
                          checked={skills.includes(skillId)}
                          onChange={() =>
                            setSkills((previous) =>
                              previous.includes(skillId)
                                ? previous.filter((entry) => entry !== skillId)
                                : [...previous, skillId],
                            )
                          }
                        />
                        {skillId}
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className={primaryButtonClass}
                disabled={busy === `grants:${editingUser}`}
                onClick={() => void saveGrants()}
              >
                {t("Save access")}
              </button>
              <button type="button" className={buttonClass} onClick={() => setEditingUser(null)}>
                {t("Cancel")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

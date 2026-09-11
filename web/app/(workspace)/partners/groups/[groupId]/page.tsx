"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Loader2,
  PanelRight,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import PartnerAvatar from "@/components/partners/PartnerAvatar";
import PartnerGroupChat from "@/components/partners/group/PartnerGroupChat";
import GroupSessionPicker from "@/components/partners/group/GroupSessionPicker";
import DiscussionModePicker, {
  useDiscussionModeLabel,
} from "@/components/partners/group/DiscussionModePicker";
import {
  deletePartnerGroup,
  getPartnerGroup,
  updatePartnerGroup,
  createPartnerGroupSessionKey,
  partnerGroupSessionKey,
  setPartnerGroupSessionKey,
  type PartnerGroup,
} from "@/lib/partner-groups-api";
import { listPartners, type PartnerInfo } from "@/lib/partners-api";

export default function PartnerGroupPage() {
  const { t } = useTranslation();
  const params = useParams<{ groupId: string }>();
  const router = useRouter();
  const groupId = decodeURIComponent(params.groupId);
  const modeLabel = useDiscussionModeLabel();

  const [group, setGroup] = useState<PartnerGroup | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [sessionKey, setSessionKey] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getPartnerGroup(groupId);
      setGroup(data);
      // Which thread is open is per-browser state, so it can only be resolved
      // here on the client — opening the group also decides its discussion.
      setSessionKey(partnerGroupSessionKey(groupId));
    } catch {
      setGroup(null);
    } finally {
      setLoading(false);
    }
  }, [groupId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (!group) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-[13px] text-[var(--muted-foreground)]">
          {t("Partner Group not found")}
        </p>
        <Link href="/partners" className="text-[12px] text-[var(--primary)]">
          {t("Back to Partners")}
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-[var(--border)] px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/partners"
            className="shrink-0 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            aria-label={t("Back to Partners")}
          >
            <ArrowLeft size={17} />
          </Link>
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-lg"
            style={{ backgroundColor: `${group.color}2e`, color: group.color }}
          >
            {group.emoji || "👥"}
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-[14px] font-semibold text-[var(--foreground)]">
              {group.name}
            </h1>
            <div className="mt-0.5 flex items-center gap-2 text-[10.5px] text-[var(--muted-foreground)]">
              <span>
                {t("{{count}} members", { count: group.member_ids.length })}
              </span>
              <span>·</span>
              <span>{modeLabel(group.discussion_mode)}</span>
              <div className="flex -space-x-1.5">
                {group.members.slice(0, 5).map((member) => (
                  <PartnerAvatar
                    key={member.partner_id}
                    name={member.name}
                    emoji={member.emoji}
                    color={member.color}
                    image={member.avatar}
                    size={18}
                    className="ring-1 ring-[var(--background)]"
                  />
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {sessionKey ? (
            <GroupSessionPicker
              groupId={groupId}
              sessionKey={sessionKey}
              onSelect={(key) => {
                setPartnerGroupSessionKey(groupId, key);
                setSessionKey(key);
              }}
              onCreate={() =>
                setSessionKey(createPartnerGroupSessionKey(groupId))
              }
            />
          ) : null}
          <button
            type="button"
            onClick={() => setPanelOpen((value) => !value)}
            className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] transition-colors ${
              panelOpen
                ? "border-[var(--ring)] text-[var(--foreground)]"
                : "border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            <PanelRight size={12} />
            {t("Details")}
          </button>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-[11px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <Pencil size={12} />
            {t("Manage")}
          </button>
        </div>
      </header>

      <PartnerGroupChat
        group={group}
        sessionKey={sessionKey}
        panelOpen={panelOpen}
        onOpenPanel={() => setPanelOpen(true)}
        onClosePanel={() => setPanelOpen(false)}
      />

      {editing ? (
        <ManageGroupDialog
          group={group}
          onClose={() => setEditing(false)}
          onSaved={(updated) => {
            setGroup(updated);
            setEditing(false);
          }}
          onDeleted={() => router.push("/partners")}
        />
      ) : null}
    </div>
  );
}

function ManageGroupDialog({
  group,
  onClose,
  onSaved,
  onDeleted,
}: {
  group: PartnerGroup;
  onClose: () => void;
  onSaved: (group: PartnerGroup) => void;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const [partners, setPartners] = useState<PartnerInfo[]>([]);
  const [name, setName] = useState(group.name);
  const [description, setDescription] = useState(group.description);
  const [members, setMembers] = useState<Set<string>>(
    new Set(group.member_ids),
  );
  const [mode, setMode] = useState(group.discussion_mode);
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void listPartners()
      .then(setPartners)
      .catch(() => setPartners([]));
  }, []);

  const toggle = (partnerId: string) => {
    setMembers((current) => {
      const next = new Set(current);
      if (next.has(partnerId)) next.delete(partnerId);
      else next.add(partnerId);
      return next;
    });
  };

  const save = async () => {
    if (!name.trim() || members.size < 2) return;
    setSaving(true);
    setError("");
    try {
      onSaved(
        await updatePartnerGroup(group.group_id, {
          name: name.trim(),
          description: description.trim(),
          member_ids: Array.from(members),
          discussion_mode: mode,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Action failed"));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await deletePartnerGroup(group.group_id);
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Action failed"));
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="max-h-[86vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--background)] p-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
            {t("Manage Partner Group")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <X size={17} />
          </button>
        </div>

        <label className="mt-5 block text-[11px] font-medium text-[var(--muted-foreground)]">
          {t("Name")}
        </label>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
        />

        <label className="mt-4 block text-[11px] font-medium text-[var(--muted-foreground)]">
          {t("Description")}
        </label>
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={2}
          className="mt-1.5 w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[12px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
        />

        <div className="mt-5">
          <DiscussionModePicker
            value={mode}
            onChange={setMode}
            title={t("How they discuss")}
          />
        </div>

        <div className="mt-5 flex items-baseline justify-between">
          <span className="text-[11px] font-medium text-[var(--muted-foreground)]">
            {t("Members")}
          </span>
          <span className="text-[10.5px] text-[var(--muted-foreground)]">
            {t("{{count}} selected · at least 2", { count: members.size })}
          </span>
        </div>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {partners.map((partner) => {
            const active = members.has(partner.partner_id);
            return (
              <button
                key={partner.partner_id}
                type="button"
                onClick={() => toggle(partner.partner_id)}
                className={`flex items-center gap-2 rounded-xl border p-2.5 text-left transition-colors ${
                  active
                    ? "border-[var(--primary)] bg-[var(--primary)]/[0.04]"
                    : "border-[var(--border)] hover:border-[var(--ring)]"
                }`}
              >
                <PartnerAvatar
                  name={partner.name}
                  emoji={partner.emoji}
                  color={partner.color}
                  image={partner.avatar}
                  size={26}
                />
                <span className="min-w-0 flex-1 truncate text-[11.5px] text-[var(--foreground)]">
                  {partner.name}
                </span>
              </button>
            );
          })}
        </div>

        {error ? (
          <p className="mt-3 text-[11px] text-red-500">{error}</p>
        ) : null}

        <div className="mt-6 flex items-center justify-between gap-3">
          {confirmingDelete ? (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={remove}
                className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-red-500 px-2.5 text-[11px] font-medium text-white"
              >
                <Trash2 size={12} />
                {t("Delete permanently")}
              </button>
              <button
                type="button"
                onClick={() => setConfirmingDelete(false)}
                className="text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                {t("Cancel")}
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmingDelete(true)}
              className="inline-flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)] transition-colors hover:text-red-500"
            >
              <Trash2 size={12} />
              {t("Delete group")}
            </button>
          )}
          <button
            type="button"
            onClick={save}
            disabled={saving || !name.trim() || members.size < 2}
            className="rounded-lg bg-[var(--primary)] px-4 py-2 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
          >
            {saving ? t("Saving…") : t("Save")}
          </button>
        </div>
      </div>
    </div>
  );
}

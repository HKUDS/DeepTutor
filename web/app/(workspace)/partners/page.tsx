"use client";

/**
 * Partners — IM-connected companions driven by the chat agent loop.
 *
 * List page: one card per partner, plus the groups they form. Groups are a
 * peer concept rather than a sub-page, so the whole roster — who you can talk
 * to alone and who you can convene — is visible in one place.
 */

import { FeaturePage, PageHeader, pageActionClass, pageGridClass } from '@/components/layout/FeaturePage'
import { useEffect, useState } from "react";
import Link from "next/link";
import { HeartHandshake, Loader2, Plus, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { listPartners, type PartnerInfo } from "@/lib/partners-api";
import { listPartnerGroups, type PartnerGroup } from "@/lib/partner-groups-api";
import { formatRelativeTime } from "@/lib/relative-time";
import ChannelIcon from "@/components/partners/ChannelIcon";
import { useDiscussionModeLabel } from "@/components/partners/group/DiscussionModePicker";
import PartnerAvatar from "@/components/partners/PartnerAvatar";

function channelNames(partner: PartnerInfo): string[] {
  if (Array.isArray(partner.channels)) {
    return partner.channels.filter(
      (n) => n !== "send_progress" && n !== "send_tool_hints",
    );
  }
  return [];
}

export default function PartnersPage() {
  const modeLabel = useDiscussionModeLabel();
  const { t, i18n } = useTranslation();
  // Anyone may build partners of their own; an admin may also assign theirs to
  // other people. The list returns both — the caller's own partners in full and
  // assigned ones as identity cards — so there is one source either way.
  const [partners, setPartners] = useState<PartnerInfo[]>([]);
  const [groups, setGroups] = useState<PartnerGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const anyAssigned = partners.some((partner) => partner.can_manage === false);
  // A group needs at least two members, so the entry point stays inert until
  // there is something to convene.
  const canFormGroup = partners.length >= 2;

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [partnerList, groupList] = await Promise.all([
        listPartners().catch(() => [] as PartnerInfo[]),
        listPartnerGroups().catch(() => [] as PartnerGroup[]),
      ]);
      if (cancelled) return;
      setPartners(partnerList);
      setGroups(groupList);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <FeaturePage>
      <PageHeader
        title={t("Partners")}
        description={anyAssigned
          ? t("Your companions, plus the ones shared with you — each with its own soul, library, and channels.")
          : t("Companions with their own soul, library, and channels — reachable from your IM apps.")}
        action={
        <Link
          href="/partners/new"
          className={pageActionClass()}
        >
          <Plus className="h-3.5 w-3.5" />
          {t("New partner")}
        </Link>
        }
      />

      {loading ? (
        <div className="flex min-h-[320px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : partners.length === 0 ? (
        <div className="flex min-h-[360px] flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--border)] text-center">
          <HeartHandshake
            className="mb-3 h-8 w-8 text-[var(--muted-foreground)]"
            strokeWidth={1.5}
          />
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("No partners yet")}
          </p>
          <p className="mt-1.5 max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Create a partner, give it a soul and a slice of your library, then talk to it here or from Feishu, Telegram, Slack and more.",
            )}
          </p>
          <Link
            href="/partners/new"
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)]"
          >
            <Plus className="h-3.5 w-3.5" />
            {t("Create your first partner")}
          </Link>
        </div>
      ) : (
        <div className={pageGridClass(2)}>
          {partners.map((partner) => {
            const channels = channelNames(partner);
            return (
              <Link
                key={partner.partner_id}
                href={`/partners/${encodeURIComponent(partner.partner_id)}`}
                className="group flex items-start gap-3 rounded-2xl border border-[var(--border)] p-4 text-left transition-colors hover:border-[var(--ring)]"
              >
                <PartnerAvatar
                  name={partner.name}
                  emoji={partner.emoji}
                  color={partner.color}
                  image={partner.avatar}
                  size={42}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[14px] font-medium text-[var(--foreground)]">
                      {partner.name}
                    </span>
                    <span className="inline-flex shrink-0 items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
                      <span
                        aria-hidden
                        className={`h-1.5 w-1.5 rounded-full ${
                          partner.running ? "bg-emerald-500" : "bg-[var(--border)]"
                        }`}
                      />
                      {partner.running ? t("Running") : t("Stopped")}
                    </span>
                    {partner.can_manage === false ? (
                      <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10.5px] text-[var(--muted-foreground)]">
                        {t("Shared with you")}
                      </span>
                    ) : null}
                  </div>
                  {partner.description ? (
                    <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                      {partner.description}
                    </p>
                  ) : null}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {channels.length > 0 ? (
                      channels.map((channel) => (
                        <span
                          key={channel}
                          className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]"
                        >
                          <ChannelIcon name={channel} size={11} />
                          {channel}
                        </span>
                      ))
                    ) : (
                      <span className="text-[11px] text-[var(--muted-foreground)]">
                        {t("No channels connected")}
                      </span>
                    )}
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {!loading && partners.length > 0 ? (
        <section className="mt-9 border-t border-[var(--border)] pt-7">
          <PageHeader
            level={2}
            title={t("Groups")}
            description={t("Ask several Partners at once and compare how they differ.")}
            action={canFormGroup ? (
              <Link
                href="/partners/groups/new"
                className={pageActionClass('secondary')}
              >
                <Plus className="h-3.5 w-3.5" />
                {t("New group")}
              </Link>
            ) : null}
          />

          {groups.length === 0 ? (
            <div className="flex items-center gap-3 rounded-2xl border border-dashed border-[var(--border)] px-4 py-5">
              <Users
                className="h-6 w-6 shrink-0 text-[var(--muted-foreground)]"
                strokeWidth={1.5}
              />
              <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                {canFormGroup
                  ? t(
                      "Bring two or more Partners together — they share the conversation but reason on their own.",
                    )
                  : t("Create one more Partner to form your first group.")}
              </p>
            </div>
          ) : (
            <div className={pageGridClass(2)}>
              {groups.map((group) => (
                <Link
                  key={group.group_id}
                  href={`/partners/groups/${encodeURIComponent(group.group_id)}`}
                  className="group flex items-start gap-3 rounded-2xl border border-[var(--border)] p-4 text-left transition-colors hover:border-[var(--ring)]"
                >
                  <div
                    className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-2xl text-xl"
                    style={{
                      backgroundColor: `${group.color}2e`,
                      color: group.color,
                    }}
                  >
                    {group.emoji || "👥"}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14px] font-medium text-[var(--foreground)]">
                      {group.name}
                    </div>
                    {group.description ? (
                      <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                        {group.description}
                      </p>
                    ) : null}
                    <div className="mt-2 flex items-center gap-2">
                      <div className="flex -space-x-1.5">
                        {group.members.slice(0, 5).map((member) => (
                          <PartnerAvatar
                            key={member.partner_id}
                            name={member.name}
                            emoji={member.emoji}
                            color={member.color}
                            image={member.avatar}
                            size={20}
                            className="ring-2 ring-[var(--background)]"
                          />
                        ))}
                      </div>
                      <span className="truncate text-[11px] text-[var(--muted-foreground)]">
                        {t("{{count}} members", {
                          count: group.member_ids.length,
                        })}
                        {" · "}
                        {modeLabel(group.discussion_mode)}
                        {group.updated_at
                          ? ` · ${formatRelativeTime(
                              Date.parse(group.updated_at) / 1000,
                              i18n.language,
                            )}`
                          : ""}
                      </span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </FeaturePage>
  );
}

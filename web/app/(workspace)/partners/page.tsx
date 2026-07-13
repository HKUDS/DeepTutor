"use client";

/**
 * Partners — IM-connected companions driven by the chat agent loop.
 * List page: one card per partner; creation lives at /partners/new.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { HeartHandshake, Loader2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { listPartners, type PartnerInfo } from "@/lib/partners-api";
import {
  connectSubagent,
  listConnectablePartners,
  listSubagentConnections,
  type ConnectablePartner,
} from "@/lib/subagents-api";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import ChannelIcon from "@/components/partners/ChannelIcon";
import PartnerAvatar from "@/components/partners/PartnerAvatar";

function channelNames(partner: PartnerInfo): string[] {
  if (Array.isArray(partner.channels)) {
    return partner.channels.filter(
      (n) => n !== "send_progress" && n !== "send_tool_hints",
    );
  }
  return [];
}

function asPartnerInfo(card: ConnectablePartner): PartnerInfo {
  // A non-admin only ever sees identity cards (no channel wiring); normalize
  // into the shape the card grid renders, with no channels.
  return {
    partner_id: card.partner_id,
    name: card.name,
    description: card.description || "",
    channels: [],
    emoji: card.emoji,
    color: card.color,
    avatar: card.avatar,
    language: card.language,
    running: Boolean(card.running),
    started_at: null,
  };
}

export default function PartnersPage() {
  const router = useRouter();
  const { t } = useTranslation();
  // Partners are admin-managed: an admin sees & manages every partner, while a
  // non-admin sees only the partners assigned to them, read-only (creation and
  // editing stay admin-only). The list source differs accordingly.
  const { isAdmin, loading: authLoading } = useAuthStatus();
  const [partners, setPartners] = useState<PartnerInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Clicking a partner card. An admin drills into the management page; a
  // non-admin can't manage partners — for them a partner is consulted as a
  // connected agent, so we reuse (or create) that partner's subagent
  // connection and drop them straight into a fresh chat with it preselected.
  const openPartner = useCallback(
    async (partner: PartnerInfo) => {
      if (isAdmin) {
        router.push(`/partners/${partner.partner_id}`);
        return;
      }
      setBusyId(partner.partner_id);
      try {
        const conns = await listSubagentConnections();
        const existing = conns.find(
          (c) =>
            c.agent_kind === "partner" && c.partner_id === partner.partner_id,
        );
        let name = existing?.name;
        if (!name) {
          const taken = new Set(conns.map((c) => c.name));
          const base = partner.name?.trim() || partner.partner_id;
          let candidate = base;
          for (let i = 2; taken.has(candidate); i++)
            candidate = `${base} (${i})`;
          name = (
            await connectSubagent({
              name: candidate,
              agent_kind: "partner",
              partner_id: partner.partner_id,
            })
          ).name;
        }
        router.push(`/home?agent=${encodeURIComponent(name)}`);
      } catch {
        // Couldn't auto-connect (e.g. the name clashes with an existing KB) —
        // fall back to My Agents, where the partner can be connected by hand.
        router.push("/agents");
      } finally {
        setBusyId(null);
      }
    },
    [isAdmin, router],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (isAdmin) {
        setPartners(await listPartners());
      } else {
        setPartners((await listConnectablePartners()).map(asPartnerInfo));
      }
    } catch {
      setPartners([]);
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    if (authLoading) return;
    void load();
  }, [authLoading, load]);

  return (
    <div className="mx-auto h-full max-w-4xl overflow-y-auto px-6 py-8">
      <header className="mb-7 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[19px] font-semibold tracking-tight text-[var(--foreground)]">
            {t("Partners")}
          </h1>
          <p className="mt-1 text-[12.5px] text-[var(--muted-foreground)]">
            {isAdmin
              ? t(
                  "Companions with their own soul, library, and channels — reachable from your IM apps.",
                )
              : t(
                  "Partners your administrator has assigned to you. Click one to start chatting with it.",
                )}
          </p>
        </div>
        {isAdmin ? (
          <Link
            href="/partners/new"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] hover:opacity-90"
          >
            <Plus className="h-3.5 w-3.5" />
            {t("New partner")}
          </Link>
        ) : null}
      </header>

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
            {isAdmin ? t("No partners yet") : t("No partners assigned yet")}
          </p>
          <p className="mt-1.5 max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {isAdmin
              ? t(
                  "Create a partner, give it a soul and a slice of your library, then talk to it here or from Feishu, Telegram, Slack and more.",
                )
              : t(
                  "Your administrator hasn't assigned you any partners yet. Once they do, they'll appear here.",
                )}
          </p>
          {isAdmin ? (
            <Link
              href="/partners/new"
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)]"
            >
              <Plus className="h-3.5 w-3.5" />
              {t("Create your first partner")}
            </Link>
          ) : null}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {partners.map((partner) => {
            const channels = channelNames(partner);
            return (
              <button
                key={partner.partner_id}
                type="button"
                onClick={() => void openPartner(partner)}
                disabled={busyId === partner.partner_id}
                className="group flex items-start gap-3 rounded-2xl border border-[var(--border)] p-4 text-left transition-colors hover:border-[var(--ring)] disabled:opacity-60"
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
                    {busyId === partner.partner_id ? (
                      <Loader2 className="h-3 w-3 shrink-0 animate-spin text-[var(--muted-foreground)]" />
                    ) : (
                      <span
                        title={partner.running ? t("Running") : t("Stopped")}
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                          partner.running
                            ? "bg-emerald-500"
                            : "bg-[var(--border)]"
                        }`}
                      />
                    )}
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
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

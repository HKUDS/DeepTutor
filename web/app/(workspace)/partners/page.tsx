"use client";

/**
 * Partners — IM-connected companions driven by the chat agent loop.
 * List page: one card per partner; creation lives at /partners/new.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { HeartHandshake, Loader2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { listPartners, type PartnerInfo } from "@/lib/partners-api";
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

export default function PartnersPage() {
  const { t } = useTranslation();
  // Anyone may build partners of their own; an admin may also assign theirs to
  // other people. The list returns both — the caller's own partners in full and
  // assigned ones as identity cards — so there is one source either way.
  const [partners, setPartners] = useState<PartnerInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const anyAssigned = partners.some((partner) => partner.can_manage === false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPartners(await listPartners());
    } catch {
      setPartners([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto h-full max-w-4xl overflow-y-auto px-6 py-8">
      <header className="mb-7 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[19px] font-semibold tracking-tight text-[var(--foreground)]">
            {t("Partners")}
          </h1>
          <p className="mt-1 text-[12.5px] text-[var(--muted-foreground)]">
            {anyAssigned
              ? t(
                  "Your companions, plus the ones shared with you — each with its own soul, library, and channels.",
                )
              : t(
                  "Companions with their own soul, library, and channels — reachable from your IM apps.",
                )}
          </p>
        </div>
        <Link
          href="/partners/new"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] hover:opacity-90"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("New partner")}
        </Link>
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
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
                    <span
                      title={partner.running ? t("Running") : t("Stopped")}
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        partner.running
                          ? "bg-emerald-500"
                          : "bg-[var(--border)]"
                      }`}
                    />
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
    </div>
  );
}

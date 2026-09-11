"use client";

import { useState } from "react";
import { ListChecks } from "lucide-react";
import { useTranslation } from "react-i18next";

import PartnerAvatar from "@/components/partners/PartnerAvatar";
import type { PartnerGroupMember } from "@/lib/partner-groups-api";

/**
 * Close a round by having one member sum it up.
 *
 * Deliberately an action rather than a discussion mode: before seeing the
 * answers you do not know whether you need a summary, and a mode would force
 * that decision up front. Offered only once a round actually has several
 * answers to reconcile.
 */
export default function RoundSummaryAction({
  members,
  onSummarize,
}: {
  members: PartnerGroupMember[];
  onSummarize: (partnerId: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  if (!members.length) return null;

  return (
    <div className="relative flex justify-center pt-1">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[10.5px] text-[var(--muted-foreground)] transition-opacity hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus:opacity-100 sm:opacity-0 sm:group-hover/round:opacity-100"
      >
        <ListChecks size={11} />
        {t("Summarise this round")}
      </button>

      {open ? (
        <div
          className="absolute bottom-full z-30 mb-1 w-[210px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-xl"
          onMouseLeave={() => setOpen(false)}
        >
          <div className="px-2.5 pb-1 pt-0.5 text-[9.5px] text-[var(--muted-foreground)]">
            {t("Who should sum it up?")}
          </div>
          {members.map((member) => (
            <button
              key={member.partner_id}
              type="button"
              onClick={() => {
                setOpen(false);
                onSummarize(member.partner_id);
              }}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--muted)]"
            >
              <PartnerAvatar
                name={member.name}
                emoji={member.emoji}
                color={member.color}
                image={member.avatar}
                size={18}
              />
              <span className="truncate text-[11.5px] text-[var(--foreground)]">
                {member.name}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

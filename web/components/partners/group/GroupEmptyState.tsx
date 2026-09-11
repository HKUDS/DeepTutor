"use client";

import { useTranslation } from "react-i18next";

import PartnerAvatar from "@/components/partners/PartnerAvatar";
import type { PartnerGroupMember } from "@/lib/partner-groups-api";

/**
 * The resting state of an empty group.
 *
 * A panel's value is the mix of people in it, so the empty state shows who is
 * actually in the room — with each member's own one-liner — instead of a
 * generic icon. That answers "what can I get here?" before the first message,
 * and it is real data rather than invented prompt suggestions.
 */
export default function GroupEmptyState({
  members,
  mode,
}: {
  members: PartnerGroupMember[];
  /** What will actually happen when they ask — the modes differ visibly. */
  mode: string;
}) {
  const { t } = useTranslation();

  // The resting state is the last moment before the first question, so it has
  // to describe the mode that is actually configured. Saying "everyone answers
  // from their own angle" while the group is set to debate is simply wrong.
  const modeHint =
    mode === "sequential"
      ? t(
          "Ask once and they answer in turn — each one sees what came before and builds on it.",
        )
      : mode === "debate"
        ? t(
            "Ask once and they each take a position, then respond to where they disagree.",
          )
        : t("Ask once and every Partner answers from their own angle.");

  return (
    <div className="flex min-h-[340px] flex-col items-center justify-center px-4 text-center">
      <div className="flex flex-wrap items-start justify-center gap-x-6 gap-y-4">
        {members.map((member) => (
          <div
            key={member.partner_id}
            className="flex w-[124px] flex-col items-center gap-1.5"
          >
            <PartnerAvatar
              name={member.name}
              emoji={member.emoji}
              color={member.color}
              image={member.avatar}
              size={40}
            />
            <span className="max-w-full truncate text-[12px] font-medium text-[var(--foreground)]">
              {member.name}
            </span>
            {member.description ? (
              <span className="line-clamp-2 text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
                {member.description}
              </span>
            ) : null}
          </div>
        ))}
      </div>

      <h2 className="mt-7 text-[14.5px] font-medium text-[var(--foreground)]">
        {t("Start a group discussion")}
      </h2>
      <p className="mt-1.5 max-w-md text-[12px] leading-relaxed text-[var(--muted-foreground)]">
        {modeHint} {t("Use @name to narrow it down.")}
      </p>
    </div>
  );
}

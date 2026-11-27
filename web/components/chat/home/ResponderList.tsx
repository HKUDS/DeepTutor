"use client";

/**
 * Everyone a side chat can be opened with, as menu rows: Dito first, then the
 * connected agents and partner groups, and the partners last — usually the
 * longest list, so it is the one left to scroll. The selection
 * toolbar and the viewer launcher both open side chats from it, so the two
 * never offer different people.
 */

import type { ReactNode } from "react";
import { Bot, MessagesSquare, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { agentGlyph } from "@/components/agents/agent-icons";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import { usePartnerGroups } from "@/hooks/usePartnerGroups";
import { usePartnerRoster } from "@/hooks/usePartnerRoster";
import { DITO, type SideChatResponder } from "@/lib/side-chat";

export default function ResponderList({
  agents,
  aboutConversation = true,
  onPick,
}: {
  /** Connected agents (not partners) this account can talk to. */
  agents: { name: string; kind?: string }[];
  /** There is a conversation for Dito to have read. */
  aboutConversation?: boolean;
  onPick: (responder: SideChatResponder) => void;
}) {
  const { t } = useTranslation();
  const { partners } = usePartnerRoster(true);
  const { groups } = usePartnerGroups(true);
  return (
    <>
      <MenuSection label={t("Open a side chat with")}>
        <MenuRow
          icon={<MessagesSquare size={15} strokeWidth={1.7} />}
          label="Dito"
          detail={
            aboutConversation ? t("Has read this conversation") : undefined
          }
          onClick={() => onPick(DITO)}
        />
      </MenuSection>
      {agents.length > 0 ? (
        <MenuSection label={t("Agents")}>
          {agents.map((agent) => {
            // Held in an object: the glyph is a module constant, not a component made here.
            const glyph = { Icon: agentGlyph(agent.kind) ?? Bot };
            return (
              <MenuRow
                key={agent.name}
                icon={<glyph.Icon size={15} />}
                label={agent.name}
                onClick={() =>
                  onPick({ kind: "subagent", id: agent.name, name: agent.name })
                }
              />
            );
          })}
        </MenuSection>
      ) : null}
      {groups.length > 0 ? (
        <MenuSection label={t("Partner groups")}>
          {groups.map((group) => (
            <MenuRow
              key={group.group_id}
              icon={
                group.emoji ? (
                  <span className="text-[14px] leading-none">
                    {group.emoji}
                  </span>
                ) : (
                  <UsersRound size={15} strokeWidth={1.7} />
                )
              }
              label={group.name}
              onClick={() =>
                onPick({
                  kind: "partner_group",
                  id: group.group_id,
                  name: group.name,
                })
              }
            />
          ))}
        </MenuSection>
      ) : null}
      {partners.length > 0 ? (
        <MenuSection label={t("Partners")}>
          {partners.map((partner) => (
            <MenuRow
              key={partner.partner_id}
              icon={
                <PartnerAvatar
                  name={partner.name}
                  emoji={partner.emoji}
                  color={partner.color}
                  image={partner.avatar}
                  size={18}
                  className="shrink-0"
                />
              }
              label={partner.name}
              onClick={() =>
                onPick({
                  kind: "partner",
                  id: partner.partner_id,
                  name: partner.name,
                })
              }
            />
          ))}
        </MenuSection>
      ) : null}
    </>
  );
}

function MenuSection({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div role="group" aria-label={label} className="py-0.5">
      <div className="px-2.5 pb-1 pt-1.5 text-[11px] font-medium text-[var(--muted-foreground)]">
        {label}
      </div>
      {children}
    </div>
  );
}

function MenuRow({
  icon,
  label,
  detail,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  detail?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--muted)] focus-visible:bg-[var(--muted)] focus-visible:outline-none"
    >
      <span className="flex size-5 shrink-0 items-center justify-center text-[var(--muted-foreground)]">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px]">{label}</span>
        {detail ? (
          <span className="block truncate text-[11px] text-[var(--muted-foreground)]">
            {detail}
          </span>
        ) : null}
      </span>
    </button>
  );
}

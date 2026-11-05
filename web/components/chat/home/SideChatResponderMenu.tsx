"use client";

/**
 * Who answers in a side chat — the far end of its composer tray.
 *
 * In the main chat this end holds two menus: who DeepTutor works with, and
 * who answers at all. A side chat has one question only, because who answers
 * is what the side chat is: Dito, a partner, a partner group (convened by
 * Dito), or a connected agent. Picking another hands the next message to
 * them; what was already said stays in the thread.
 */

import type { ReactNode } from "react";
import { Bot, MessagesSquare, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { agentGlyph, agentKindLabel } from "@/components/agents/agent-icons";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import ResponderFace from "./ResponderFace";
import { usePartnerGroups } from "@/hooks/usePartnerGroups";
import { usePartnerRoster } from "@/hooks/usePartnerRoster";
import { DITO, sameResponder, type SideChatResponder } from "@/lib/side-chat";
import {
  TrayList,
  TrayMenu,
  TrayOption,
  TraySection,
  type TrayPlacement,
} from "./ComposerTrayMenu";

export default function SideChatResponderMenu({
  value,
  onChange,
  agents,
  aboutConversation,
  placement = "up",
}: {
  value: SideChatResponder;
  /** The side chat is about a conversation Dito has read. */
  aboutConversation: boolean;
  onChange: (responder: SideChatResponder) => void;
  /** Connected agents (not partners) this account can talk to. */
  agents: { name: string; kind?: string }[];
  placement?: TrayPlacement;
}) {
  const { t } = useTranslation();
  const { partners, loading } = usePartnerRoster(true);
  const { groups } = usePartnerGroups(true);
  const partner =
    value.kind === "partner"
      ? partners.find((item) => item.partner_id === value.id)
      : undefined;
  const agent =
    value.kind === "subagent"
      ? agents.find((item) => item.name === value.id)
      : undefined;
  const group =
    value.kind === "partner_group"
      ? groups.find((item) => item.group_id === value.id)
      : undefined;

  const name =
    value.kind === "partner"
      ? (partner?.name ?? value.name)
      : value.kind === "partner_group"
        ? (group?.name ?? value.name)
        : value.kind === "subagent"
          ? value.name
          : "Dito";

  return (
    <TrayMenu
      icon={<ResponderFace responder={value} agents={agents} size={14} />}
      label={t("Answered by")}
      value={name}
      active={value.kind !== "dito"}
      placement={placement}
      align="end"
    >
      {(close) => {
        const pick = (responder: SideChatResponder) => {
          if (!sameResponder(responder, value)) onChange(responder);
          close();
        };
        const row = (
          responder: SideChatResponder,
          leading: ReactNode,
          title: string,
          meta?: string,
        ) => (
          <TrayOption
            key={`${responder.kind}:${"id" in responder ? responder.id : ""}`}
            selected={sameResponder(responder, value)}
            onSelect={() => pick(responder)}
            leading={leading}
            title={title}
            meta={meta}
          />
        );
        return (
          <TrayList label={t("Answered by")}>
            <TraySection title={t("Answered by")}>
              {row(
                DITO,
                <MessagesSquare size={14} strokeWidth={1.7} />,
                "Dito",
                aboutConversation ? t("Has read this conversation") : undefined,
              )}
            </TraySection>
            {agents.length > 0 && (
              <TraySection title={t("Agents")}>
                {agents.map((item) => {
                  const glyph = { Icon: agentGlyph(item.kind) ?? Bot };
                  return row(
                    { kind: "subagent", id: item.name, name: item.name },
                    <glyph.Icon size={15} />,
                    item.name,
                    agentKindLabel(item.kind) || undefined,
                  );
                })}
              </TraySection>
            )}
            {groups.length > 0 && (
              <TraySection
                title={t("Partner groups")}
                hint={t(
                  "Dito convenes the group and brings back what it said.",
                )}
              >
                {groups.map((item) =>
                  row(
                    {
                      kind: "partner_group",
                      id: item.group_id,
                      name: item.name,
                    },
                    item.emoji ? (
                      <span className="text-[14px] leading-none">
                        {item.emoji}
                      </span>
                    ) : (
                      <UsersRound size={15} strokeWidth={1.7} />
                    ),
                    item.name,
                  ),
                )}
              </TraySection>
            )}
            {partners.length > 0 && (
              <TraySection title={t("Partners")}>
                {partners.map((item) =>
                  row(
                    { kind: "partner", id: item.partner_id, name: item.name },
                    <PartnerAvatar
                      name={item.name}
                      emoji={item.emoji}
                      color={item.color}
                      image={item.avatar}
                      size={22}
                      className="shrink-0"
                    />,
                    item.name,
                    item.description || undefined,
                  ),
                )}
              </TraySection>
            )}
            {loading && <p className="dt-tray-empty">{t("Loading...")}</p>}
          </TrayList>
        );
      }}
    </TrayMenu>
  );
}

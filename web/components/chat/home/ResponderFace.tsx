"use client";

/**
 * The mark for whoever answers a side chat: a partner's own avatar, a partner
 * group's emoji, a connected agent's glyph, Dito's speech bubbles. Tabs and the
 * composer's responder menu both draw it, so a side chat looks like the one
 * it is with wherever it shows.
 */

import { Bot, MessagesSquare, UsersRound } from "lucide-react";
import { agentGlyph } from "@/components/agents/agent-icons";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import { usePartnerGroups } from "@/hooks/usePartnerGroups";
import { usePartnerRoster } from "@/hooks/usePartnerRoster";
import type { SideChatResponder } from "@/lib/side-chat";

export default function ResponderFace({
  responder,
  agents = [],
  size = 14,
}: {
  responder: SideChatResponder;
  /** Connected agents, to tell one agent's kind (and glyph) from another's. */
  agents?: { name: string; kind?: string }[];
  size?: number;
}) {
  const { partners } = usePartnerRoster(responder.kind === "partner");
  const { groups } = usePartnerGroups(responder.kind === "partner_group");
  if (responder.kind === "partner") {
    const partner = partners.find((item) => item.partner_id === responder.id);
    return (
      <PartnerAvatar
        name={partner?.name ?? responder.name}
        emoji={partner?.emoji}
        color={partner?.color}
        image={partner?.avatar}
        size={size + 2}
        className="shrink-0"
      />
    );
  }
  if (responder.kind === "partner_group") {
    const emoji = groups.find((item) => item.group_id === responder.id)?.emoji;
    return emoji ? (
      <span
        aria-hidden="true"
        className="shrink-0 leading-none"
        style={{ fontSize: size - 1 }}
      >
        {emoji}
      </span>
    ) : (
      <UsersRound size={size} strokeWidth={1.8} className="shrink-0" />
    );
  }
  if (responder.kind === "subagent") {
    const kind = agents.find((item) => item.name === responder.id)?.kind;
    // Held in an object: the glyph is a module constant, not a component made here.
    const glyph = { Icon: agentGlyph(kind) ?? Bot };
    return <glyph.Icon size={size} className="shrink-0" />;
  }
  return <MessagesSquare size={size} strokeWidth={1.8} className="shrink-0" />;
}

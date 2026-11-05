"use client";

import { Bot } from "lucide-react";
import { agentGlyph } from "@/components/agents/agent-icons";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import { usePartner } from "@/hooks/usePartnerRoster";
import type { Answerer } from "./answerer";

/**
 * Who is answering, where DeepTutor's orb would be.
 *
 * A partner shows its own face — its picture when the shared partner list
 * has it, else the emoji and colour the turn itself carries. A connected
 * agent shows its brand mark on a soft tile, so the two never read alike.
 * While the turn is running a ring breathes around the mark: the same
 * "still working" the orb's motion says, in the answerer's own shape.
 */
export function AnswererMark({
  answerer,
  working = false,
  size = 18,
}: {
  answerer: Answerer;
  working?: boolean;
  size?: number;
}) {
  const partner = usePartner(answerer.kind === "partner" ? answerer.id : null);
  // Held in an object, as elsewhere: the glyph is a module constant, not a component made here.
  const glyph = { Icon: agentGlyph(answerer.agent) ?? Bot };
  return (
    <span
      aria-hidden
      data-kind={answerer.kind}
      className={`dt-answerer-mark${working ? " is-working" : ""}`}
      style={{ width: size, height: size }}
    >
      {answerer.kind === "partner" ? (
        <PartnerAvatar
          name={partner?.name ?? answerer.name}
          emoji={partner?.emoji ?? answerer.emoji}
          color={partner?.color ?? answerer.color}
          image={partner?.avatar}
          size={size}
        />
      ) : (
        <span className="dt-answerer-tile">
          <glyph.Icon size={Math.round(size * 0.66)} />
        </span>
      )}
    </span>
  );
}

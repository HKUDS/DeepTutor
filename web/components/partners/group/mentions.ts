/**
 * @mention parsing for Partner Group messages.
 *
 * The composer resolves mentions to partner ids itself and sends them
 * explicitly, rather than letting the backend re-parse the prose. That keeps
 * two properties the text protocol cannot give us: a display name containing
 * spaces still resolves, and an unrecognised @token can be surfaced in the
 * composer instead of failing the whole message server-side.
 */

import type { PartnerGroupMember } from "@/lib/partner-groups-api";

/** Tokens that address the whole panel, in both supported UI languages. */
const EVERYONE_TOKENS = new Set(["all", "everyone", "所有人", "全部", "大家"]);

/** A raw @token stops at whitespace, another @, or sentence punctuation. */
const MENTION_TOKEN = /(?<![\w@])@([^\s@,，、:：;；!?！？。.]+)/g;

export interface ResolvedMentions {
  /** Partner ids to address; empty means "everyone" (the @all default). */
  targets: string[];
  /** Members matching ``targets``, in group member order. */
  members: PartnerGroupMember[];
  /** @tokens that matched no member — shown as a hint, never a hard failure. */
  unknown: string[];
  /** Whether the text explicitly addressed everyone (@all). */
  everyone: boolean;
}

function aliasIndex(members: PartnerGroupMember[]): Map<string, string> {
  const index = new Map<string, string>();
  for (const member of members) {
    index.set(member.partner_id.toLowerCase(), member.partner_id);
    if (member.name) index.set(member.name.toLowerCase(), member.partner_id);
  }
  return index;
}

/**
 * Resolve the @mentions in ``text`` against the group roster.
 *
 * A display name may contain spaces, which no single token regex can capture,
 * so each raw token is also extended greedily against the roster: for "@Ada
 * Lovelace" the token "Ada" fails, but the longest roster alias starting at
 * that offset wins.
 */
export function resolveMentions(
  text: string,
  members: PartnerGroupMember[],
): ResolvedMentions {
  const aliases = aliasIndex(members);
  const targets: string[] = [];
  const unknown: string[] = [];
  let everyone = false;

  for (const match of text.matchAll(MENTION_TOKEN)) {
    const token = match[1];
    const lower = token.toLowerCase();
    if (EVERYONE_TOKENS.has(lower)) {
      everyone = true;
      continue;
    }
    const direct = aliases.get(lower);
    if (direct) {
      if (!targets.includes(direct)) targets.push(direct);
      continue;
    }
    // Multi-word display name: match the longest alias present at this offset.
    const rest = text.slice((match.index ?? 0) + 1).toLowerCase();
    const spanned = [...aliases.keys()]
      .filter((alias) => alias.includes(" ") && rest.startsWith(alias))
      .sort((a, b) => b.length - a.length)[0];
    if (spanned) {
      const id = aliases.get(spanned)!;
      if (!targets.includes(id)) targets.push(id);
      continue;
    }
    if (!unknown.includes(token)) unknown.push(token);
  }

  const ordered = members
    .filter((member) => targets.includes(member.partner_id))
    .map((member) => member.partner_id);

  return {
    targets: everyone ? [] : ordered,
    members: members.filter((member) => ordered.includes(member.partner_id)),
    unknown,
    everyone,
  };
}

/** The trailing "@partial" the caret is currently typing, or null. */
export function activeMentionQuery(text: string): string | null {
  const match = /(?:^|\s)@([^\s@]*)$/.exec(text);
  return match ? match[1] : null;
}

/** Members matching the in-progress @query, in group member order. */
export function mentionSuggestions(
  query: string,
  members: PartnerGroupMember[],
): PartnerGroupMember[] {
  const lower = query.toLowerCase();
  if (!lower) return members;
  return members.filter(
    (member) =>
      member.name.toLowerCase().includes(lower) ||
      member.partner_id.toLowerCase().includes(lower),
  );
}

/**
 * Replace the in-progress "@partial" with a completed mention.
 *
 * The display name is inserted because that is what the user reads; the
 * composer sends resolved ids alongside, so a name with spaces is still safe.
 */
export function completeMention(
  text: string,
  member: PartnerGroupMember,
): string {
  return text.replace(/@[^\s@]*$/, `@${member.name || member.partner_id} `);
}

export { EVERYONE_TOKENS };

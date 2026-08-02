/**
 * Turn-navigator model — "where did I ask that?" for long transcripts.
 *
 * A chat outline is one entry per *user* turn on the currently-visible
 * branch, carrying just enough to render a rail tick plus its hover
 * preview: the question text, the opening of the reply it produced, and
 * a relative weight used to size the tick.
 *
 * Everything here is pure so the navigator's behaviour is testable
 * without a DOM: the only coupling to the rendered transcript is
 * ``turnAnchorKey``, which both this module and ``UserMessage`` use to
 * agree on a stable ``data-turn-key`` per bubble.
 */

import type { MessageItem } from "@/context/UnifiedChatContext";
import { buildVisiblePath } from "@/lib/message-branches";

/**
 * Backend grounding the user never typed (quiz scoring hand-off). It is
 * filtered from the bubble list in ``UserMessage``, so it must not earn
 * a tick either.
 */
const SYNTHETIC_USER_PREFIX = "[Quiz Performance]";

export interface ChatOutlineEntry {
  /** Matches the ``data-turn-key`` attribute on the rendered bubble. */
  key: string;
  messageId?: number;
  /** Position in the visible path (the ``index`` prop of ``UserMessage``). */
  index: number;
  /** 1-based question number, as counted by the user. */
  ordinal: number;
  /** The question, flattened to a single line. */
  title: string;
  /** Opening of the assistant reply this question produced ("" if none). */
  reply: string;
  capability?: string;
  /** 0..1, question length relative to the longest one in this session. */
  weight: number;
}

/**
 * Stable DOM key for a message bubble. Persisted rows key off their
 * server id; an optimistic (negative-id) or id-less row falls back to
 * its position, which is stable for as long as it is on screen.
 */
export function turnAnchorKey(
  message: Pick<MessageItem, "id">,
  index: number,
): string {
  return message.id != null ? `m${message.id}` : `i${index}`;
}

/**
 * Flatten markdown to a single line of readable prose.
 *
 * This is a preview, not a renderer: fenced code, images, tables and
 * link targets carry no signal at 12 px in a 300 px card, so they are
 * dropped rather than escaped. Order matters — block constructs are
 * removed before inline ones so their markers don't survive as debris.
 */
export function plainTextPreview(markdown: string, maxLength = 160): string {
  if (!markdown) return "";
  let text = markdown;
  // Block level.
  text = text.replace(/```[\s\S]*?(?:```|$)/g, " ");
  text = text.replace(/~~~[\s\S]*?(?:~~~|$)/g, " ");
  text = text.replace(/^\s{0,3}(?:[-*_]\s*){3,}$/gm, " ");
  text = text.replace(/^\s{0,3}>+\s?/gm, "");
  text = text.replace(/^\s{0,3}#{1,6}\s+/gm, "");
  text = text.replace(/^\s{0,3}(?:[-*+]|\d+[.)])\s+/gm, "");
  // Inline.
  text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, " ");
  text = text.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1");
  text = text.replace(/<[^>\n]{1,120}>/g, " ");
  text = text.replace(/`([^`]*)`/g, "$1");
  text = text.replace(/(\*\*|__|~~)(.*?)\1/g, "$2");
  text = text.replace(/(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])/g, "$1");
  // Artifact / citation annotations the renderer consumes invisibly.
  text = text.replace(/\[\^[^\]]*\]/g, " ");
  text = text.replace(/\{\{[^}]*\}\}/g, " ");
  text = text.replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trimEnd()}…`;
}

/**
 * One entry per user turn on the visible branch, in reading order.
 *
 * The walk mirrors ``ChatMessageList``: it runs over the same
 * ``buildVisiblePath`` result, so switching an edit branch reshapes the
 * rail exactly the way it reshapes the transcript, and indices line up
 * with the ``index`` prop each bubble receives.
 */
export function buildChatOutline(
  messages: MessageItem[],
  selectedBranches?: Record<string, number>,
): ChatOutlineEntry[] {
  const { messages: visible } = buildVisiblePath(messages, selectedBranches);
  const entries: ChatOutlineEntry[] = [];

  for (let index = 0; index < visible.length; index += 1) {
    const msg = visible[index];
    if (msg.role !== "user") continue;
    if (msg.content.startsWith(SYNTHETIC_USER_PREFIX)) continue;
    const title = plainTextPreview(msg.content, 160);
    if (!title) continue;

    // The reply is the first assistant row before the next question.
    // Deep Research splits one question across two assistant turns and
    // the planning turn can be content-free, hence the scan.
    let reply = "";
    for (let j = index + 1; j < visible.length; j += 1) {
      const next = visible[j];
      if (next.role === "user") break;
      if (next.role !== "assistant") continue;
      const preview = plainTextPreview(next.content, 160);
      if (preview) {
        reply = preview;
        break;
      }
    }

    entries.push({
      key: turnAnchorKey(msg, index),
      messageId: msg.id,
      index,
      ordinal: entries.length + 1,
      title,
      reply,
      capability: msg.capability,
      weight: 0,
    });
  }

  // Weight is relative *within the session* so the rail reads as a
  // fingerprint of this conversation rather than of some absolute scale.
  // Square-root compression keeps one long paste from flattening every
  // other tick to the minimum.
  const longest = entries.reduce((max, e) => Math.max(max, e.title.length), 0);
  if (longest > 0) {
    for (const entry of entries) {
      entry.weight = Math.sqrt(entry.title.length / longest);
    }
  }
  return entries;
}

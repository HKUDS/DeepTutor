/**
 * Edit-branching tree helpers.
 *
 * The server stores all messages as a flat list per session, with
 * ``parent_message_id`` pointers — siblings share the same parent and
 * represent alternative continuations created by editing a user message.
 *
 * The UI shows a single linear path at a time. ``buildVisiblePath`` picks
 * that path from the flat list: starting at the root (parent = null), at
 * every branch point it follows ``selectedBranches[parent_id]`` if set,
 * otherwise it falls back to the latest-created child (the one most
 * recently added — including the still-in-flight optimistic message which
 * uses a negative client-side id and is treated as newer than any
 * persisted positive id).
 */

import type { MessageItem } from "@/context/UnifiedChatContext";

const ROOT_KEY = "null";

function parentKey(id: number | null | undefined): string {
  return id == null ? ROOT_KEY : String(id);
}

// Large offset that pushes every optimistic (negative-id) sibling above
// every persisted (positive-id) sibling without overflowing safe-integer
// arithmetic. ``Date.now()`` lives around 1.7e12 today, so 1e15 leaves
// ample headroom and stays well under ``Number.MAX_SAFE_INTEGER``.
const OPTIMISTIC_RANK_OFFSET = 1e15;

function siblingRank(message: MessageItem): number {
  // Optimistic, in-flight messages get a negative ``id`` on the client
  // (``-Date.now()``) and must be treated as the freshest sibling so the
  // bubble the user just submitted stays visible. Among optimistic rows,
  // the *more recent* one (more negative id) must rank higher so that a
  // second optimistic send doesn't get hidden by the first. Persisted
  // messages keep their natural id-ordered rank.
  const id = message.id ?? 0;
  return id < 0 ? OPTIMISTIC_RANK_OFFSET - id : id;
}

export interface SiblingInfo {
  /** Number of alternative branches at this point, including this one. */
  total: number;
  /** 1-based index of the current branch in chronological order. */
  index: number;
  /** All sibling message ids in chronological (creation) order. */
  siblingIds: number[];
  /** Parent message id (``null`` if at the session root). */
  parentId: number | null;
}

export interface VisiblePathResult {
  /** The flat message list to render, in chronological order. */
  messages: MessageItem[];
  /** Sibling info keyed by message id. Only present for messages whose
   *  parent has more than one child (i.e. branching points). */
  siblingsByMessageId: Map<number, SiblingInfo>;
}

export function buildVisiblePath(
  allMessages: MessageItem[],
  selectedBranches: Record<string, number> | undefined,
): VisiblePathResult {
  // Group by parent.
  const childrenByParent = new Map<string, MessageItem[]>();
  for (const msg of allMessages) {
    if (msg.id === undefined) continue;
    const key = parentKey(msg.parentMessageId);
    const arr = childrenByParent.get(key);
    if (arr) arr.push(msg);
    else childrenByParent.set(key, [msg]);
  }
  for (const arr of childrenByParent.values()) {
    arr.sort((a, b) => siblingRank(a) - siblingRank(b));
  }

  const selection = selectedBranches ?? {};
  const visible: MessageItem[] = [];
  const siblingsByMessageId = new Map<number, SiblingInfo>();
  const guard = new Set<string>();
  let currentParent = ROOT_KEY;
  // Bound the walk defensively against pathological data (loops).
  let safety = 10_000;
  while (safety > 0) {
    safety -= 1;
    if (guard.has(currentParent)) break;
    guard.add(currentParent);
    const children = childrenByParent.get(currentParent);
    if (!children || children.length === 0) break;

    let chosen: MessageItem;
    if (children.length === 1) {
      chosen = children[0];
    } else {
      const selectedId = selection[currentParent];
      chosen =
        (selectedId !== undefined &&
          children.find((c) => c.id === selectedId)) ||
        children[children.length - 1];
    }
    visible.push(chosen);

    if (children.length > 1 && chosen.id !== undefined) {
      const idx = children.findIndex((c) => c.id === chosen.id);
      siblingsByMessageId.set(chosen.id, {
        total: children.length,
        index: idx + 1,
        siblingIds: children.map((c) => c.id!).filter((id) => id !== undefined),
        parentId: chosen.parentMessageId ?? null,
      });
    }

    if (chosen.id === undefined) break;
    currentParent = String(chosen.id);
  }

  return { messages: visible, siblingsByMessageId };
}

/**
 * Find the most recent child id under ``parentId`` from a flat message
 * list. Used after an edit to auto-select the freshly persisted sibling.
 * Persisted (positive-id) rows only — optimistic in-flight rows aren't
 * useful as a persisted selection target.
 */
export function latestChildId(
  allMessages: MessageItem[],
  parentId: number | null,
): number | null {
  const key = parentKey(parentId);
  let best: number | null = null;
  let bestId = 0;
  for (const m of allMessages) {
    if (parentKey(m.parentMessageId) !== key) continue;
    if (m.id === undefined || m.id <= 0) continue;
    if (m.id > bestId) {
      bestId = m.id;
      best = m.id;
    }
  }
  return best;
}

/**
 * Compute the parent id of the next message a user would send right now
 * given the currently-visible path. Returns the last visible message's
 * id (incl. optimistic in-flight rows whose ``id`` is a negative client
 * sentinel) so a follow-up message chains under the active branch even
 * when no server reload has reconciled real ids yet. ``null`` for an
 * empty session.
 */
export function tipMessageId(visible: MessageItem[]): number | null {
  for (let i = visible.length - 1; i >= 0; i -= 1) {
    const id = visible[i].id;
    if (id !== undefined) return id;
  }
  return null;
}

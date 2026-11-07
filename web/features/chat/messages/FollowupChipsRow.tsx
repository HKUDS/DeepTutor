"use client";

/**
 * FollowupChipsRow — fetches and renders the one-click reactions offered under
 * the latest answer, on any surface that renders its own message list
 * (the home chat, a mastery sitting, reading).
 *
 * The set is chosen server-side (`deeptutor/services/chat_followups.py`); this
 * only fetches it once per settled turn and hands a pick back as a normal turn.
 */

import { useEffect, useState } from "react";

import FollowupChips from "@/features/chat/messages/FollowupChips";
import {
  fetchSessionFollowups,
  type FollowupSuggestion,
} from "@/lib/session-api";

export default function FollowupChipsRow({
  sessionId,
  isStreaming,
  /** Changes once per settled turn (the message count works). */
  turnKey,
  /** True when the last message is an assistant answer. */
  enabled,
  onFollowup,
}: {
  sessionId?: string | null;
  isStreaming: boolean;
  turnKey: number;
  enabled: boolean;
  onFollowup?: (prompt: string) => void;
}) {
  // Keyed by turn so a set from an earlier answer never shows under a new one.
  const [loaded, setLoaded] = useState<{
    key: number;
    rows: FollowupSuggestion[];
  } | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    if (!enabled || isStreaming || !sessionId || !onFollowup) return;
    let cancelled = false;
    void fetchSessionFollowups(sessionId).then((rows) => {
      if (!cancelled) {
        setLoaded({ key: turnKey, rows });
        setOffset(0);
      }
    });
    return () => {
      cancelled = true;
    };
    // `onFollowup` must be stable (a useCallback / adapter method); callers pass
    // one so this fires once per settled turn, not on every render.
  }, [enabled, isStreaming, sessionId, turnKey, onFollowup]);

  if (
    !enabled ||
    !onFollowup ||
    !loaded ||
    loaded.key !== turnKey ||
    loaded.rows.length === 0
  ) {
    return null;
  }

  return (
    <FollowupChips
      suggestions={loaded.rows}
      offset={offset}
      onCycle={() => setOffset((current) => (current + 4) % loaded.rows.length)}
      onPick={onFollowup}
    />
  );
}

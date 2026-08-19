export type WhisperSeat = "visitor" | "trainee";

export type WhisperMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  stage?: string;
  source?: string;
  localSeat?: WhisperSeat; // optimistic user bubble
};

export function parseRoomIdFromContent(text: string): string | null {
  const m = /room_id=([A-Za-z0-9_-]+)/.exec(text || "");
  return m ? m[1] : null;
}

export function filterMessagesForSeat(
  messages: WhisperMessage[],
  seat: WhisperSeat,
): WhisperMessage[] {
  if (seat === "trainee") return messages;
  return messages.filter((msg) => {
    if (msg.stage === "whisper") return false;
    if (msg.source === "whisper_trainee" && msg.stage === "debrief") return false;
    return true;
  });
}

/**
 * Detect visitor-facing crisis redirect copy from psych_academy/safety/redirect.py
 * (_EN / _ZH). Match distinctive substrings from the real templates.
 */
export function looksLikeCrisisRedirect(text: string): boolean {
  const t = (text || "").toLowerCase();
  return (
    t.includes("cannot provide crisis intervention") ||
    t.includes("i am concerned you may be in danger") ||
    t.includes("不能做危机干预") ||
    t.includes("可能处于危险中") ||
    // optional helpline_text appended by render_redirect
    t.includes("转介") ||
    t.includes("热线")
  );
}

/**
 * Detect trainee-facing crisis summary from whisper_trainee._CRISIS_SUMMARY.
 */
export function looksLikeTraineeCrisisSummary(text: string): boolean {
  const t = (text || "").toLowerCase();
  return (
    t.includes("closed for crisis referral") ||
    t.includes("no further counseling or whispers")
  );
}

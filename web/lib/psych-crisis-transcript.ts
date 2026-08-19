/**
 * Shared crisis redirect + room_id parsing for academy surfaces
 * (counsel, intake). Whisper-specific filtering lives in #921.
 */

export function parseRoomIdFromContent(text: string): string | null {
  const m = /room_id=([A-Za-z0-9_-]+)/.exec(text || "");
  return m ? m[1] : null;
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
    t.includes("转介") ||
    t.includes("热线")
  );
}

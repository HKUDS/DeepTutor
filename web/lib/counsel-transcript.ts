/**
 * Counsel /counsel page helpers — crisis redirect + session terminal copy.
 * Reuses psych-academy redirect templates (same strings as whisper visitor).
 */

export { looksLikeCrisisRedirect } from "@/lib/whisper-transcript";

export function looksLikeCounselSessionEnded(text: string): boolean {
  const t = (text || "").toLowerCase();
  return (
    t.includes("counseling session has ended") ||
    t.includes("咨询会话已结束") ||
    t.includes("start a new session_id")
  );
}

export function looksLikeCarePlanClose(text: string): boolean {
  return (text || "").includes("Care plan:");
}

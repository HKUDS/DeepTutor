/** Text/metadata helpers shared by the provider adapters. */

import type { ImportSource } from "./types";

/** Human-facing name for each importable agent source. */
export const SOURCE_LABEL: Record<ImportSource, string> = {
  claude_code: "Claude Code",
  codex: "Codex",
};

// Harness-injected context the user never typed — stripped so imported
// transcripts read like a human conversation.
const SYSTEM_REMINDER_RE = /<system-reminder>[\s\S]*?<\/system-reminder>/g;

export function cleanText(text: string): string {
  return text.replace(SYSTEM_REMINDER_RE, "").trim();
}

/** Convert an ISO timestamp to epoch seconds, falling back when absent. */
export function isoToEpochSeconds(iso: unknown, fallback: number): number {
  if (typeof iso !== "string") return fallback;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms / 1000 : fallback;
}

/** Local calendar day `YYYY-MM-DD` for an epoch-ms timestamp. Used as the
 *  date selection unit (Codex groups by day) and to bucket sessions by day. */
export function epochMsToISODate(ms: number): string {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** A short, single-line title derived from a message body. */
export function deriveTitle(text: string, max = 80): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  if (oneLine.length <= max) return oneLine;
  return oneLine.slice(0, max).trimEnd() + "…";
}

/** Last path segment of a working directory, for a compact project label. */
export function projectLabel(cwd: string): string {
  const parts = cwd.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : cwd || "(unknown)";
}

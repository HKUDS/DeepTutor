/**
 * Map imported sessions (which live on the backend) back to the client-side
 * agents that own them. An agent's identity lives in IndexedDB, so this is how
 * both the Space management page and the chat reference picker decide which
 * conversations belong to which named agent.
 */

import type { SessionSummary } from "@/lib/session-api";
import type { ImportAgent } from "./agent-store";
import { epochMsToISODate } from "./shared";
import type { AgentScope, ImportSource } from "./types";

export interface SessionImportMeta {
  source: ImportSource;
  sourceCwd: string;
  agentId?: string;
}

export function readImportMeta(
  session: SessionSummary,
): SessionImportMeta | null {
  const imp = (
    session.preferences as
      | { import?: { source?: string; source_cwd?: string; agent_id?: string } }
      | undefined
  )?.import;
  const src = imp?.source;
  if (src !== "claude_code" && src !== "codex") return null;
  return {
    source: src,
    sourceCwd: imp?.source_cwd ?? "",
    agentId: imp?.agent_id || undefined,
  };
}

/** Which selection unit a session falls under, for scope membership tests. */
export function sessionUnitKey(
  source: ImportSource,
  meta: SessionImportMeta,
  createdAtSec: number,
): string {
  return source === "codex"
    ? epochMsToISODate(createdAtSec * 1000)
    : meta.sourceCwd;
}

export function scopeContainsSession(
  scope: AgentScope,
  meta: SessionImportMeta,
  createdAtSec: number,
): boolean {
  if (scope.kind === "all") return true;
  if (scope.kind === "projects") return scope.cwds.includes(meta.sourceCwd);
  return scope.days.includes(epochMsToISODate(createdAtSec * 1000));
}

/**
 * Assign each imported session to exactly one agent: by explicit `agent_id`
 * when present, else by source + scope membership. The fallback re-attaches
 * conversations imported before the agent model and migrated legacy agents
 * (whose scope is `all`). Returns sessionId → agentId; unmatched maps to null.
 */
export function assignSessionsToAgents(
  sessions: SessionSummary[],
  agents: ImportAgent[],
): Map<string, string | null> {
  const byId = new Map(agents.map((a) => [a.id, a]));
  const out = new Map<string, string | null>();
  for (const session of sessions) {
    const sid = session.session_id || session.id;
    const meta = readImportMeta(session);
    if (!meta) {
      out.set(sid, null);
      continue;
    }
    if (meta.agentId && byId.has(meta.agentId)) {
      out.set(sid, meta.agentId);
      continue;
    }
    const owner = agents.find(
      (a) =>
        a.source === meta.source &&
        scopeContainsSession(a.scope, meta, session.created_at),
    );
    out.set(sid, owner?.id ?? null);
  }
  return out;
}

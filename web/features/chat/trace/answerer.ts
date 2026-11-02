import type { StreamEvent } from "@/features/chat/model/protocol";

/**
 * Whoever a handed-over turn was given to, as its events name them.
 *
 * The handoff capability tags every event it writes with `delegate_*`
 * fields, and its result carries the same card as `answered_by`. A live
 * turn has the tags from its first event; a settled one keeps at least the
 * result in its preview — so either finds the answerer.
 */
export interface Answerer {
  kind: "partner" | "subagent";
  id: string;
  name: string;
  emoji?: string;
  color?: string;
  /** A connected agent's backend kind, for its brand mark. */
  agent?: string;
}

function card(source: Record<string, unknown>, prefix: string): Answerer | undefined {
  const read = (key: string) => {
    const value = source[`${prefix}${key}`];
    return typeof value === "string" && value ? value : undefined;
  };
  const kind = read("kind");
  const name = read("name");
  if ((kind !== "partner" && kind !== "subagent") || !name) return undefined;
  return {
    kind,
    id: read("id") ?? name,
    name,
    emoji: read("emoji"),
    color: read("color"),
    agent: read("agent"),
  };
}

export function answererOf(events: readonly StreamEvent[] | undefined): Answerer | undefined {
  for (const event of events ?? []) {
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    const tagged = card(meta, "delegate_");
    if (tagged) return tagged;
    if (event.type === "result") {
      const nested = (meta.metadata as { answered_by?: Record<string, unknown> } | undefined)?.answered_by;
      const answered = nested ? card(nested, "") : undefined;
      if (answered) return answered;
    }
  }
  return undefined;
}

/** `partner:<id>` / `subagent:<name>` → its parts; null for anything else. */
export function parseAnswerBy(value: unknown): { kind: Answerer["kind"]; id: string } | null {
  if (typeof value !== "string") return null;
  const at = value.indexOf(":");
  const kind = value.slice(0, at);
  const id = value.slice(at + 1).trim();
  if ((kind === "partner" || kind === "subagent") && id) return { kind, id };
  return null;
}

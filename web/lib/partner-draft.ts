import type { StreamEvent } from "@/features/chat/model/protocol";
import { toolResultMetadata } from "@/lib/tool-event";

/** Versioned payload emitted by the Chat engine's `propose_partner` tool. */
export interface PartnerDraftData {
  draft_id: string;
  owner_id: string;
  name: string;
  description: string;
  soul: string;
  language: string;
  emoji: string;
  color: string;
  status: "pending" | "created";
  created_partner_id?: string;
  version: number;
}

export function extractPartnerDraft(
  events: StreamEvent[] | undefined,
): PartnerDraftData | null {
  if (!events) return null;
  let latest: PartnerDraftData | null = null;
  for (const event of events) {
    if (event.type !== "tool_result") continue;
    const raw = toolResultMetadata(event.metadata)?.partner_draft;
    if (!raw || typeof raw !== "object") continue;
    const payload = raw as Record<string, unknown>;
    const draftId = String(payload.draft_id ?? "").trim();
    const name = String(payload.name ?? "").trim();
    const soul = String(payload.soul ?? "").trim();
    if (!/^[a-f0-9]{32}$/.test(draftId) || !name || !soul) continue;
    latest = {
      draft_id: draftId,
      owner_id: String(payload.owner_id ?? ""),
      name,
      description: String(payload.description ?? ""),
      soul,
      language: String(payload.language ?? ""),
      emoji: String(payload.emoji ?? ""),
      color: String(payload.color ?? ""),
      status: payload.status === "created" ? "created" : "pending",
      created_partner_id: String(payload.created_partner_id ?? ""),
      version: Number(payload.version ?? 1),
    };
  }
  return latest;
}

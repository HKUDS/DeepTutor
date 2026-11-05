import type { StreamEvent } from "@/features/chat/model/protocol";
import { toolResultMetadata } from "@/lib/tool-event";
import { isCreationKind, type CreationKind } from "@/lib/creations";

export interface CreationDraftReference {
  path: string;
  size: number;
  /** Omitted by the backend today, but the card can expand a reference to
   *  show it when present. */
  content: string;
}

/** Versioned payload emitted by the Chat engine's `propose_creation` tool —
 *  see `deeptutor/services/creations/drafts.py` `CreationDraft.to_dict()`. */
export interface CreationDraftData {
  draft_id: string;
  owner_id: string;
  kind: CreationKind;
  session_id: string;
  name: string;
  description: string;
  content: string;
  tags: string[];
  references: CreationDraftReference[];
  status: "pending" | "created";
  created_name: string;
  replaced: boolean;
  created_at: string;
  approved_at: string | null;
  version: number;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item ?? "")).filter(Boolean);
}

function asReferences(value: unknown): CreationDraftReference[] {
  if (!Array.isArray(value)) return [];
  const out: CreationDraftReference[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const path = String(row.path ?? "").trim();
    if (!path) continue;
    out.push({
      path,
      size: Number(row.size ?? 0) || 0,
      content: typeof row.content === "string" ? row.content : "",
    });
  }
  return out;
}

/**
 * Reads the latest `creation_draft` tool-result metadata out of a message's
 * events. Defensive like `extractPartnerDraft`: a payload missing optional
 * fields degrades to sensible defaults rather than being dropped, but a
 * malformed id or an unrecognised kind is rejected outright.
 */
export function extractCreationDraft(
  events: StreamEvent[] | undefined,
): CreationDraftData | null {
  if (!events) return null;
  let latest: CreationDraftData | null = null;
  for (const event of events) {
    if (event.type !== "tool_result") continue;
    const raw = toolResultMetadata(event.metadata)?.creation_draft;
    if (!raw || typeof raw !== "object") continue;
    const payload = raw as Record<string, unknown>;
    const draftId = String(payload.draft_id ?? "").trim();
    const kind = payload.kind;
    const name = String(payload.name ?? "").trim();
    if (!/^[a-f0-9]{32}$/.test(draftId) || !isCreationKind(kind) || !name) continue;
    latest = {
      draft_id: draftId,
      owner_id: String(payload.owner_id ?? ""),
      kind,
      session_id: String(payload.session_id ?? ""),
      name,
      description: String(payload.description ?? ""),
      content: String(payload.content ?? ""),
      tags: asStringArray(payload.tags),
      references: asReferences(payload.references),
      status: payload.status === "created" ? "created" : "pending",
      created_name: String(payload.created_name ?? ""),
      replaced: Boolean(payload.replaced),
      created_at: String(payload.created_at ?? ""),
      approved_at: typeof payload.approved_at === "string" ? payload.approved_at : null,
      version: Number(payload.version ?? 1),
    };
  }
  return latest;
}

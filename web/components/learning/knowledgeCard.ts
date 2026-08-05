import type { KnowledgeBaseSummary } from "@/lib/knowledge-api";
import type { KnowledgeCardMutationResult, KnowledgeCardView } from "@/lib/knowledge-card-api";

/* ────────────────────────────────────────────────────────────────────────
 * Knowledge-card review/publication contract helpers (UI-02).
 *
 * Pure and React-free so node tests exercise them directly. Implements the
 * writable-KB classification, the per-status action availability, the pending
 * card filter and the failure-assurance text rules — all server-authoritative
 * in that the client never loosens a domain invariant (editing requires a
 * ``draft``, discard requires ``draft``/``stale_evidence``, generation retry
 * requires an un-locked draft whose latest attempt has terminated, etc.).
 * ──────────────────────────────────────────────────────────────────────── */

export const CARD_STATUSES = [
  "draft",
  "stale_evidence",
  "publishing",
  "published",
  "publish_failed",
  "reconcile_required",
  "retracting",
  "retract_reconcile_required",
  "retracted",
  "discarded",
] as const;

export type CardStatus = (typeof CARD_STATUSES)[number];

/** Statuses that no longer occupy the knowledge-point slot (§7.9). */
const NON_OCCUPYING: ReadonlySet<string> = new Set(["stale_evidence", "discarded", "retracted"]);

export function isCardStatus(value: string): value is CardStatus {
  return (CARD_STATUSES as readonly string[]).includes(value);
}

/** Pending display = everything except discarded/retracted (§13.5). */
export function pendingCards(cards: KnowledgeCardView[]): KnowledgeCardView[] {
  return cards.filter((card) => card.status !== "discarded" && card.status !== "retracted");
}

export type KbDisableReason =
  | "connected"
  | "assigned"
  | "read_only"
  | "unavailable"
  | "error"
  | "indexing"
  | "needs_reindex";

const CONNECTED_KB_TYPES = new Set([
  "obsidian",
  "linked",
  "subagent",
  "lightrag_server",
  "ima",
]);

const STATUS_REASON: Record<string, KbDisableReason> = {
  needs_reindex: "needs_reindex",
  error: "error",
  unavailable: "unavailable",
  indexing: "indexing",
  processing: "indexing",
  initializing: "indexing",
  creating: "indexing",
  connected: "connected",
};

export function kbDisableReason(kb: KnowledgeBaseSummary): KbDisableReason | null {
  if (kb.available === false) return "unavailable";
  const type = kb.metadata?.type;
  // Connected KBs (Obsidian, linked, subagent, LightRAG server, IMA) are
  // read-only pointers — surface the connected reason before the generic
  // read_only flag so the approved "Connected · 只读" label wins (§8.5).
  if (typeof type === "string" && CONNECTED_KB_TYPES.has(type)) return "connected";
  if (kb.assigned === true) return "assigned";
  if (kb.read_only === true) return "read_only";
  if (kb.metadata?.needs_reindex === true) return "needs_reindex";
  const status = kb.status ?? "";
  if (status in STATUS_REASON) return STATUS_REASON[status];
  // A local, owned, indexed KB that reports ready (or predates status flags and
  // has no connected/assigned/read-only markers) is the only writable target.
  if (status === "ready" || status === "") return null;
  return "unavailable";
}

export interface KbOption {
  name: string;
  isDefault: boolean;
  writable: boolean;
  disableReason: KbDisableReason | null;
  status: string;
  provenanceLabel: string;
}

/** Sort writable KBs first, then stable-by-name; each stays in the list. */
export function classifyKbs(kbs: KnowledgeBaseSummary[]): KbOption[] {
  return kbs
    .map((kb) => {
      const reason = kbDisableReason(kb);
      return {
        name: kb.name,
        isDefault: kb.is_default === true,
        writable: reason === null,
        disableReason: reason,
        status: kb.status ?? "",
        provenanceLabel: kb.provenance_label ?? "",
      };
    })
    .sort((a, b) => {
      if (a.writable !== b.writable) return a.writable ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
}

export function anyWritableKb(kbs: KbOption[]): boolean {
  return kbs.some((kb) => kb.writable);
}

/* ── per-status action availability (§13.5, §15) ───────────────────────── */

export interface CardActionSet {
  canEdit: boolean;
  canSaveDraft: boolean;
  canRetryGeneration: boolean;
  canPublish: boolean;
  canRetryPublish: boolean;
  canReconcilePublication: boolean;
  canDiscard: boolean;
  canRetract: boolean;
  canReconcileRetraction: boolean;
}

const TERMINATED_ATTEMPT = new Set(["failed", "unknown", "superseded_by_edit"]);

export function cardActions(card: KnowledgeCardView): CardActionSet {
  const status = card.status;
  const draft = status === "draft";
  const generationAvailable =
    draft &&
    !card.generation_locked_by_user_edit &&
    card.latest_generation_attempt !== null &&
    TERMINATED_ATTEMPT.has(card.latest_generation_attempt.status);
  return {
    canEdit: draft,
    canSaveDraft: draft,
    canRetryGeneration: generationAvailable,
    canPublish: draft || status === "publish_failed",
    canRetryPublish: status === "publish_failed",
    canReconcilePublication:
      status === "reconcile_required" || status === "publish_failed",
    canDiscard: status === "draft" || status === "stale_evidence",
    canRetract: status === "published",
    canReconcileRetraction: status === "retract_reconcile_required",
  };
}

/** True while a mutation is in flight — repeated mutations are disabled. */
export function anyCardBusy(busy: Record<string, boolean>): boolean {
  return Object.values(busy).some(Boolean);
}

/** The card's non-editable reason, shown when only view/discard are allowed. */
export function readOnlyReason(card: KnowledgeCardView): string | null {
  if (card.status === "stale_evidence") return "stale_evidence";
  if (card.status === "publishing") return "publishing";
  if (card.status === "published") return "published";
  if (card.status === "retracting") return "retracting";
  if (card.status === "retracted") return "retracted";
  if (card.status === "discarded") return "discarded";
  if (card.status === "reconcile_required") return "reconcile_required";
  if (card.status === "retract_reconcile_required") return "retract_reconcile_required";
  return null;
}

/* ── generation status display ──────────────────────────────────────────── */

export type GenerationSurface =
  | "queued"
  | "running"
  | "unknown"
  | "failed"
  | "superseded_by_edit"
  | "ready"
  | "none";

export function generationSurface(card: KnowledgeCardView): GenerationSurface {
  const attempt = card.latest_generation_attempt;
  if (!attempt) return "none";
  if (attempt.status === "queued" || attempt.status === "running") {
    return attempt.status as GenerationSurface;
  }
  if (attempt.status === "unknown") return "unknown";
  if (attempt.status === "failed") return "failed";
  if (attempt.status === "superseded_by_edit") return "superseded_by_edit";
  return "ready";
}

/** Exact failure-assurance copy keys (§13.5): draft retained, no duplicate
 *  document on retry, stable mastery untouched. */
export type FailureAssurance =
  | { kind: "publish_failed" }
  | { kind: "reconcile_required" }
  | { kind: "retract_reconcile_required" }
  | null;

export function failureAssurance(card: KnowledgeCardView): FailureAssurance {
  if (card.status === "publish_failed") return { kind: "publish_failed" };
  if (card.status === "reconcile_required") return { kind: "reconcile_required" };
  if (card.status === "retract_reconcile_required") return { kind: "retract_reconcile_required" };
  return null;
}

/**
 * Merge a KB-03/KB-04 projection onto the full card view after a mutation.
 * Publication/retraction projections are a subset of the full card; the UI
 * refreshes the collection afterwards, but the merge shows the new status and
 * provenance immediately (never an invented intermediate state).
 */
export function mergeMutationResult(
  card: KnowledgeCardView,
  result: KnowledgeCardMutationResult,
): KnowledgeCardView {
  return {
    ...card,
    status: result.status,
    revision: result.revision,
    target_kb_name: result.target_kb_name,
    document_rel_path: result.document_rel_path,
    document_sha256: result.document_sha256,
    publication_key: result.publication_key,
    quarantine_rel_path: result.quarantine_rel_path,
    retraction_request_id: result.retraction_request_id,
    retraction_operation_id: result.retraction_operation_id,
    confirmed_at: result.confirmed_at,
    published_at: result.published_at,
    retracted_at: result.retracted_at,
    cleanup_status: result.cleanup_status,
    cleanup_error: result.cleanup_error,
    error_code: result.error_code,
    sanitized_error: result.sanitized_error,
  };
}

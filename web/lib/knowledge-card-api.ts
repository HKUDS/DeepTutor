import { apiFetch, apiUrl } from "./api";

/* ────────────────────────────────────────────────────────────────────────
 * KB-02/KB-03/KB-04 knowledge-card client contract (UI-02).
 *
 * Mirrors the mastery_path router adapters: owner-scoped card collection,
 * server-derived draft create/resume, versioned edit/discard/retry, and the
 * already-reviewed publication/retraction mutations. Every mutation carries
 * ``expected_card_revision`` + ``request_id``; a stale revision or reused key
 * is a recoverable 409 the UI can refresh from.
 *
 * Only audit-safe fields are expected from the backend (§14): a base-URL
 * fingerprint, never the private URL or credentials; sanitized diagnostics,
 * never the provider body; authenticated same-user file routes for images.
 * ──────────────────────────────────────────────────────────────────────── */

export interface KnowledgeCardGenerationAttempt {
  id: string;
  status: string;
  generation_attempt_no: number;
  retry_of_generation_attempt_id: string | null;
  input_card_revision: number;
  model_invocation_id: string | null;
  output_hash: string | null;
  error_code: string | null;
  sanitized_error: string | null;
  created_at: number | null;
  started_at: number | null;
  finished_at: number | null;
}

export interface KnowledgeCardModelIdentity {
  provider: string;
  profile: string;
  model: string;
  protocol: string;
  base_url_fingerprint: string | null;
  strict_protocol: boolean;
  rubric_version: string | null;
}

export interface KnowledgeCardSource {
  id: string;
  title: string;
  locator: string;
  anchors: string[];
}

export interface KnowledgeCardArtifact {
  id: string;
  available: boolean;
  mime_type: string;
  width: number;
  height: number;
  sha256: string;
  preview_url: string | null;
  download_url: string | null;
  references: { id: string; owner_type: string; owner_id: string; version: number }[];
  job_id?: string;
  provider?: string;
  profile?: string;
  protocol?: string;
  model?: string;
  operation?: string;
  original_prompt?: string;
  revised_prompt?: string;
  size_bytes?: number;
  created_at?: number;
}

export interface KnowledgeCardView {
  card_id: string;
  knowledge_point_id: string;
  status: string;
  revision: number;
  version: number;
  generation_locked_by_user_edit: boolean;
  draft_generation_status: string;
  title: string;
  body: string;
  content_hash: string;
  source_snapshot_ids: string[];
  evidence_ids: string[];
  artifact_ids: string[];
  source_count: number;
  evidence_count: number;
  artifact_count: number;
  stable_assessment_id: string;
  stable_assessment_sequence: number;
  target_kb_name: string | null;
  document_rel_path: string | null;
  document_sha256: string | null;
  publication_key: string | null;
  quarantine_rel_path: string | null;
  retraction_request_id: string | null;
  retraction_operation_id: string | null;
  cleanup_status: string;
  cleanup_error: string | null;
  confirmed_at: number | null;
  published_at: number | null;
  stale_at: number | null;
  retracted_at: number | null;
  error_code: string | null;
  sanitized_error: string | null;
  latest_generation_attempt: KnowledgeCardGenerationAttempt | null;
  model_identity: KnowledgeCardModelIdentity | null;
  sources: KnowledgeCardSource[];
  artifacts: KnowledgeCardArtifact[];
  occupies_slot: boolean;
  /** ``ensure`` only: whether a brand-new shell was created. */
  created?: boolean;
}

export interface KnowledgeCardListResult {
  cards: KnowledgeCardView[];
  updated_at: number | null;
}

/**
 * Publication/retraction projections returned by the already-reviewed KB-03 /
 * KB-04 endpoints. A subset of the full card view; the UI refreshes the card
 * collection after these mutations to get the authoritative full projection.
 */
export interface KnowledgeCardMutationResult {
  card_id: string;
  status: string;
  replayed: boolean;
  revision: number;
  target_kb_name: string | null;
  document_rel_path: string | null;
  document_sha256: string | null;
  publication_key: string | null;
  quarantine_rel_path: string | null;
  retraction_request_id: string | null;
  retraction_operation_id: string | null;
  confirmed_at: number | null;
  published_at: number | null;
  retracted_at: number | null;
  cleanup_status: string;
  cleanup_error: string | null;
  error_code: string | null;
  sanitized_error: string | null;
  publication_records?: unknown[];
  retraction_records?: unknown[];
}

export interface CardError {
  status: number;
  /** Stable structured code from the backend, e.g. ``card_version_conflict``. */
  code: string;
  message: string;
}

export function isCardError(err: unknown): err is CardError {
  return (
    typeof err === "object" &&
    err !== null &&
    "status" in err &&
    typeof (err as { status?: unknown }).status === "number"
  );
}

async function readCardJson<T>(res: Response): Promise<T> {
  if (res.ok) return res.json() as Promise<T>;
  let message = `HTTP ${res.status}`;
  let code = "";
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (body && typeof body.detail === "string") {
      message = body.detail;
    } else if (body && typeof body.detail === "object" && body.detail !== null) {
      const d = body.detail as { code?: unknown; message?: unknown };
      if (typeof d.message === "string") message = d.message;
      if (typeof d.code === "string") code = d.code;
    }
  } catch {
    // non-JSON body — keep the status fallback
  }
  const err = new Error(message) as Error & { status?: number; code?: string };
  err.status = res.status;
  if (code) err.code = code;
  throw err;
}

function cardPath(pathId: string, suffix = ""): string {
  return `/api/v1/learning/progress/${encodeURIComponent(pathId)}/knowledge-cards${suffix}`;
}

// ── collection / create ──────────────────────────────────────────────────

export async function fetchKnowledgeCards(
  pathId: string,
): Promise<KnowledgeCardListResult> {
  const res = await apiFetch(apiUrl(cardPath(pathId)));
  return readCardJson<KnowledgeCardListResult>(res);
}

export async function ensureKnowledgeCard(
  pathId: string,
  kpId: string,
): Promise<KnowledgeCardView> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(pathId)}/knowledge-points/${encodeURIComponent(kpId)}/knowledge-card`,
    ),
    { method: "POST" },
  );
  return readCardJson<KnowledgeCardView>(res);
}

// ── draft edit / retry / discard ─────────────────────────────────────────

export interface EditCardBody {
  expected_card_revision: number;
  request_id: string;
  title?: string | null;
  body?: string | null;
  attach_artifact_ids?: string[];
  detach_artifact_ids?: string[];
}

export async function editKnowledgeCard(
  pathId: string,
  cardId: string,
  body: EditCardBody,
): Promise<KnowledgeCardView> {
  const res = await apiFetch(apiUrl(cardPath(pathId, `/${encodeURIComponent(cardId)}`)), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readCardJson<KnowledgeCardView>(res);
}

export interface RetryGenerationBody {
  expected_card_revision: number;
  request_id: string;
  latest_generation_attempt_id: string;
}

export async function retryCardGeneration(
  pathId: string,
  cardId: string,
  body: RetryGenerationBody,
): Promise<KnowledgeCardView> {
  const res = await apiFetch(
    apiUrl(cardPath(pathId, `/${encodeURIComponent(cardId)}/retry-generation`)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readCardJson<KnowledgeCardView>(res);
}

export interface DiscardCardBody {
  expected_card_revision: number;
  request_id: string;
}

export async function discardKnowledgeCard(
  pathId: string,
  cardId: string,
  body: DiscardCardBody,
): Promise<KnowledgeCardView> {
  const res = await apiFetch(
    apiUrl(cardPath(pathId, `/${encodeURIComponent(cardId)}/discard`)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readCardJson<KnowledgeCardView>(res);
}

// ── publication / retraction (KB-03 / KB-04, already-reviewed) ───────────

export interface PublishCardBody {
  target_kb_name: string;
  expected_card_revision: number;
  request_id: string;
}

export async function publishKnowledgeCard(
  pathId: string,
  cardId: string,
  body: PublishCardBody,
): Promise<KnowledgeCardMutationResult> {
  const res = await apiFetch(
    apiUrl(cardPath(pathId, `/${encodeURIComponent(cardId)}/publish`)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readCardJson<KnowledgeCardMutationResult>(res);
}

export interface RetryPublishBody {
  expected_card_revision: number;
  request_id: string;
  target_kb_name?: string | null;
}

export async function retryPublishKnowledgeCard(
  pathId: string,
  cardId: string,
  body: RetryPublishBody,
): Promise<KnowledgeCardMutationResult> {
  const res = await apiFetch(
    apiUrl(cardPath(pathId, `/${encodeURIComponent(cardId)}/retry-publish`)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readCardJson<KnowledgeCardMutationResult>(res);
}

export async function reconcileCardPublication(
  pathId: string,
  cardId: string,
): Promise<KnowledgeCardMutationResult> {
  const res = await apiFetch(
    apiUrl(cardPath(pathId, `/${encodeURIComponent(cardId)}/reconcile-publication`)),
    { method: "POST" },
  );
  return readCardJson<KnowledgeCardMutationResult>(res);
}

export interface RetractCardBody {
  expected_card_revision: number;
  request_id: string;
}

export async function retractKnowledgeCard(
  pathId: string,
  cardId: string,
  body: RetractCardBody,
): Promise<KnowledgeCardMutationResult> {
  const res = await apiFetch(
    apiUrl(cardPath(pathId, `/${encodeURIComponent(cardId)}/retract`)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readCardJson<KnowledgeCardMutationResult>(res);
}

export async function reconcileCardRetraction(
  pathId: string,
  cardId: string,
): Promise<KnowledgeCardMutationResult> {
  const res = await apiFetch(
    apiUrl(cardPath(pathId, `/${encodeURIComponent(cardId)}/reconcile-retraction`)),
    { method: "POST" },
  );
  return readCardJson<KnowledgeCardMutationResult>(res);
}

import { apiUrl, apiFetch } from "./api";

/* ────────────────────────────────────────────────────────────────────────
 * Feynman learning workspace client API (UI-01).
 *
 * Mirrors the LRN-03 read/write contracts (§8.2, §8.3) and the MOD-03
 * evaluator snapshot (§7.6) so the workspace never invents parallel client
 * state. Read payloads come from:
 *   - GET  /progress/{path}/map                      (map_read_payload + map_summary)
 *   - GET  /progress/{path}/attempts/{attempt}       (attempt_read_payload)
 *   - GET  /progress/{path}/reviews                  (reviews_read_payload)
 * Mutations are idempotency/version guarded by the server; a 409 maps to a
 * recoverable refresh/retry surface (never silent overwrite).
 * ──────────────────────────────────────────────────────────────────────── */

// ── Evaluator snapshot (MOD-03, §7.6) ────────────────────────────────────

export interface EvaluatorSnapshot {
  profile_id: string;
  profile_name: string;
  profile_revision: string;
  requested_provider: string;
  requested_api_protocol: string;
  requested_model: string;
  resolved_provider: string;
  resolved_api_protocol: string;
  resolved_model: string;
  auto_resolution_reason: string;
  base_url_fingerprint: string;
  strict_protocol: boolean;
  prompt_version: string;
  rubric_version: string;
  created_at: number;
}

// ── Knowledge map payload (map_read_payload + map_summary) ──────────────

export interface NextObjective {
  action: string;
  module_id: string;
  module_name: string;
  knowledge_point_id: string;
  knowledge_point_name: string;
  knowledge_point_type: string;
  status: string;
  gate: string;
  mastery: number;
  threshold: number;
  reason: string;
  pending_prompt: string;
}

export interface KnowledgeProjection {
  knowledge_point_id: string;
  mastery_state: string;
  review_state: string;
  active_attempt_id: string;
  latest_assessment_id: string;
  provisional_since: number | null;
  stable_since: number | null;
  next_review_at: number | null;
  updated_at: number;
}

export interface ActiveAttemptRef {
  attempt_id: string;
  status: string;
  cycle_type: string;
  chain_id: string;
  map_version_id: string;
}

export interface EvidenceSummary {
  count: number;
  kinds: string[];
}

export interface SourceSnapshot {
  id: string;
  source_type: string;
  material_id: string;
  locator: string;
  title: string;
  content_hash: string;
  citation_anchors: string[];
  captured_at: number;
}

export interface KnowledgeMapVersion {
  id: string;
  path_id: string;
  version: number;
  nodes: string[];
  edges: Record<string, unknown>[];
  priorities: Record<string, number>;
  source_snapshot_ids: string[];
  confirmed_at: number;
}

export interface SourceConflict {
  id: string;
  path_id: string;
  knowledge_point_ids: string[];
  claim: string;
  source_snapshot_ids: string[];
  citation_anchors: string[];
  version: number;
  status: "open" | "resolved";
  accepted_snapshot_id: string;
  resolution_note: string;
  resolved_at: number | null;
  resolved_by: string;
}

export interface MapKnowledgePoint {
  id: string;
  name: string;
  type: string;
  status: string;
  mastery: number;
}

export interface MapModule {
  id: string;
  name: string;
  order: number;
  mastered: number;
  total: number;
  knowledge_points: MapKnowledgePoint[];
}

export interface MasteryMapSummary {
  counts: { mastered: number; learning: number; new: number; total: number };
  due_reviews: number;
  complete: boolean;
  modules: MapModule[];
}

export interface FeynmanMapPayload {
  book_id: string;
  next: NextObjective;
  projections: Record<string, KnowledgeProjection>;
  active_attempts: Record<string, ActiveAttemptRef>;
  evidence_summary: Record<string, EvidenceSummary>;
  map_version: number;
  map_version_id: string;
  source_snapshots: SourceSnapshot[];
  map_versions: KnowledgeMapVersion[];
  conflicts: SourceConflict[];
  updated_at: number;
  map: MasteryMapSummary;
}

// ── Attempt detail (attempt_read_payload) ────────────────────────────────

export interface SourceCitation {
  source_snapshot_id: string;
  anchor: string;
}

export interface FeynmanAttempt {
  id: string;
  knowledge_point_id: string;
  cycle_type: string;
  status: string;
  invalidated_reason: string;
  knowledge_point_version: number;
  map_version_id: string;
  source_snapshot_ids: string[];
  supersedes_attempt_id: string;
  session_id: string;
  started_turn_id: string;
  active_chain_id: string;
  max_help_level: string;
  evaluator_snapshot: EvaluatorSnapshot | null;
  created_at: number;
  updated_at: number;
  closed_at: number | null;
}

export interface EvidenceItem {
  id: string;
  attempt_id: string;
  chain_id: string;
  kind: string;
  session_id: string;
  turn_id: string;
  message_id: string;
  event_seq: number;
  input_mode: string;
  transcript_confirmed: boolean;
  content_snapshot: string;
  content_hash: string;
  question_evidence_id: string;
  source_citations: SourceCitation[];
  help_level: string | null;
  created_at: number;
}

export interface RubricScores {
  correctness: number;
  completeness: number;
  causal_clarity: number;
  transfer: number;
}

export interface ServerGateResult {
  passed: boolean;
  required_evidence_kinds: string[];
  missing_evidence_kinds: string[];
  blocked_by_conflict: string[];
  used_full_explanation: boolean;
  reasons: string[];
}

export interface RubricAssessment {
  id: string;
  attempt_id: string;
  revision: number;
  assessment_sequence: number;
  rubric: RubricScores;
  critical_errors: string[];
  strengths: string[];
  gap_ids: string[];
  evidence_ids: string[];
  source_citations: SourceCitation[];
  evaluator_snapshot: EvaluatorSnapshot | null;
  model_invocation_id: string;
  supersedes_assessment_id: string;
  challenge_id: string;
  server_gate_result: ServerGateResult;
  created_at: number;
}

export interface GapRecord {
  id: string;
  knowledge_point_id: string;
  label: string;
  description: string;
  evidence_ids: string[];
  source_citations: SourceCitation[];
  status: string;
  priority: number;
  first_seen_at: number;
  last_seen_at: number;
  resolved_at: number | null;
}

export interface ChallengeRecord {
  id: string;
  knowledge_point_id: string;
  source_attempt_id: string;
  source_assessment_id: string;
  mode: string;
  requested_evaluator_snapshot: EvaluatorSnapshot | null;
  result_attempt_id: string;
  result_assessment_id: string;
  status: string;
  reason: string;
  created_at: number;
  completed_at: number | null;
}

export interface AttemptDetail {
  attempt: FeynmanAttempt;
  evidence: EvidenceItem[];
  assessments: RubricAssessment[];
  gaps: GapRecord[];
  challenges: ChallengeRecord[];
  audit: { seq: number; event_type: string; summary: string; at: number }[];
  projection: KnowledgeProjection | null;
}

// ── Unified review queue (reviews_read_payload) ──────────────────────────

export interface ReviewTask {
  id: string;
  knowledge_point_id: string;
  knowledge_type: string;
  due_at: number;
  priority: number;
  state: {
    interval_index: number;
    consecutive_correct: number;
    consecutive_wrong: number;
    next_review_at: number;
  };
}

export interface ReviewsPayload {
  reviews: ReviewTask[];
  due_reviews: ReviewTask[];
  due_count: number;
  needs_revision: string[];
  updated_at: number;
}

// ── Fetch helpers ────────────────────────────────────────────────────────

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body — keep the status */
    }
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}

export async function fetchFeynmanMap(pathId: string): Promise<FeynmanMapPayload> {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${encodeURIComponent(pathId)}/map`),
  );
  return readJson<FeynmanMapPayload>(res);
}

export async function fetchAttemptDetail(
  pathId: string,
  attemptId: string,
): Promise<AttemptDetail> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(pathId)}/attempts/${encodeURIComponent(attemptId)}`,
    ),
  );
  return readJson<AttemptDetail>(res);
}

export async function fetchReviews(pathId: string): Promise<ReviewsPayload> {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${encodeURIComponent(pathId)}/reviews`),
  );
  return readJson<ReviewsPayload>(res);
}

export interface ResumeResumedResult {
  status: "resumed";
  attempt_id: string;
  chain_id: string;
  cycle_type: string;
  knowledge_point_id: string;
  max_help_level: string;
  attempt_version: number;
  next_required_steps: string[];
}

export interface ResumeRestartResult {
  status: "requires_restart";
  attempt_id: string;
  invalidated_reason: string;
  map_version_id: string;
  map_version: number;
}

export interface ResumeClosedResult {
  status: "closed";
  attempt_id: string;
  cycle_type: string;
}

export type ResumeAttemptResult =
  | ResumeResumedResult
  | ResumeRestartResult
  | ResumeClosedResult;

export async function resumeAttempt(
  pathId: string,
  attemptId: string,
): Promise<ResumeAttemptResult> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(pathId)}/attempts/${encodeURIComponent(attemptId)}/resume`,
    ),
    { method: "POST" },
  );
  return readJson<ResumeAttemptResult>(res);
}

export interface ChallengeBody {
  mode: "reassess_existing" | "collect_new_evidence";
  reason: string;
  requested_evaluator_snapshot?: EvaluatorSnapshot | null;
  request_id: string;
  expected_attempt_version: number;
}

export interface ChallengeResult {
  challenge_id: string;
  mode: string;
  status: string;
  source_attempt_id: string;
  source_assessment_id: string;
  result_attempt_id: string;
  knowledge_point_id: string;
  attempt_version: number;
}

export async function createChallenge(
  pathId: string,
  attemptId: string,
  body: ChallengeBody,
): Promise<ChallengeResult> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(pathId)}/attempts/${encodeURIComponent(attemptId)}/challenge`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readJson<ChallengeResult>(res);
}

export interface MapEditBody {
  nodes: string[];
  edges: Record<string, unknown>[];
  priorities: Record<string, number>;
  expected_map_version: number;
  request_id: string;
}

export async function editMap(
  pathId: string,
  body: MapEditBody,
): Promise<Record<string, unknown>> {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${encodeURIComponent(pathId)}/map`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readJson<Record<string, unknown>>(res);
}

export interface MapConfirmBody {
  expected_map_version: number;
  request_id: string;
  source_snapshot_ids?: string[] | null;
}

export async function confirmMap(
  pathId: string,
  body: MapConfirmBody,
): Promise<Record<string, unknown>> {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${encodeURIComponent(pathId)}/map/confirm`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readJson<Record<string, unknown>>(res);
}

export interface ConflictResolveBody {
  accepted_snapshot_id: string;
  resolution_note: string;
  request_id: string;
  expected_conflict_version: number;
  expected_map_version: number;
}

export async function resolveConflict(
  pathId: string,
  conflictId: string,
  body: ConflictResolveBody,
): Promise<Record<string, unknown>> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(pathId)}/conflicts/${encodeURIComponent(conflictId)}/resolve`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readJson<Record<string, unknown>>(res);
}

export interface ConflictReopenBody {
  request_id: string;
  expected_conflict_version: number;
  expected_map_version: number;
}

export async function reopenConflict(
  pathId: string,
  conflictId: string,
  body: ConflictReopenBody,
): Promise<Record<string, unknown>> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(pathId)}/conflicts/${encodeURIComponent(conflictId)}/reopen`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readJson<Record<string, unknown>>(res);
}

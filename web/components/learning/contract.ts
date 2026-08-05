import type {
  AttemptDetail,
  EvaluatorSnapshot,
  EvidenceItem,
  FeynmanMapPayload,
  GapRecord,
  KnowledgeProjection,
  ReviewTask,
  RubricAssessment,
  SourceConflict,
} from "@/lib/feynman-learning";

/* ────────────────────────────────────────────────────────────────────────
 * Pure contract mappings: backend LRN-03 / MOD-03 payloads → render-ready UI
 * models. Kept free of React so node tests can exercise them directly.
 * ──────────────────────────────────────────────────────────────────────── */

export type StageKey = "explain" | "probe" | "transfer" | "feedback";
export type StageStatus = "done" | "active" | "todo" | "blocked";

export interface StageState {
  key: StageKey;
  /** ``active`` when it is the current stage, ``blocked`` when a full
   *  explanation invalidated the chain, ``todo``/``done`` otherwise. */
  status: StageStatus;
  /** Sub-copy, e.g. ``1/2`` for probes. Empty when not applicable. */
  count: string;
}

export type ConversationRole = "user" | "assistant" | "system";

export interface ConversationItem {
  key: string;
  role: ConversationRole;
  /** Stable semantic label key; the view localises it. */
  labelKey: string;
  kind: string;
  content: string;
  inputMode: "text" | "voice_transcript";
  transcriptConfirmed: boolean;
  helpLevel: string | null;
  createdAt: number;
}

export type MasteryTone = "new" | "in-progress" | "provisional" | "stable" | "revision";

export interface MasteryDisplay {
  masteryState: string;
  reviewState: string;
  tone: MasteryTone;
  nextReviewAt: number | null;
  activeAttemptId: string;
}

export interface RubricRow {
  key: string;
  labelKey: string;
  score: number;
  /** 0 / 1 / 2 rubric score mapping. */
  verdictKey: "pass" | "partial" | "fail" | "unset";
}

export interface WorkspaceConflict {
  conflict: SourceConflict;
  sides: { snapshot: { id: string; title: string; locator: string }; anchors: string[] }[];
  acceptedSideId: string;
}

export interface ContractError {
  kind: "recoverable" | "fatal";
  status?: number;
  message: string;
}

const REVIEW_TASK_PRIORITY_LABEL: Record<number, string> = {
  1: "high",
  2: "medium",
  3: "medium",
  4: "low",
  5: "low",
};

/* ── Conversation from evidence (§7.2) ─────────────────────────────────── */

function evidenceLabelKey(kind: string, role: ConversationRole): string {
  if (kind === "explanation") return "conversation.explanation";
  if (kind === "probe_question") return "conversation.probe";
  if (kind === "probe_answer") return "conversation.probeAnswer";
  if (kind === "transfer_question") return "conversation.transfer";
  if (kind === "transfer_answer") return "conversation.transferAnswer";
  if (kind === "reteach") return "conversation.reteach";
  if (kind === "source_reference") return "conversation.sourceRef";
  return role === "assistant" ? "conversation.assistant" : "conversation.learner";
}

export function evidenceToConversation(evidence: EvidenceItem[]): ConversationItem[] {
  const items: ConversationItem[] = evidence.map((e) => {
    const role: ConversationRole =
      e.kind === "probe_question" || e.kind === "transfer_question"
        ? "assistant"
        : e.kind === "reteach" || e.kind === "source_reference"
          ? "system"
          : "user";
    const inputMode: "text" | "voice_transcript" =
      e.input_mode === "voice_transcript" ? "voice_transcript" : "text";
    return {
      key: e.id,
      role,
      labelKey: evidenceLabelKey(e.kind, role),
      kind: e.kind,
      content: e.content_snapshot,
      inputMode,
      transcriptConfirmed: e.transcript_confirmed,
      helpLevel: e.help_level,
      createdAt: e.created_at,
    };
  });
  return items.sort((a, b) => a.createdAt - b.createdAt || a.key.localeCompare(b.key));
}

/* ── Stage bar (§6.1, §13.1) ───────────────────────────────────────────── */

function probePairs(evidence: EvidenceItem[]): number {
  const answers = new Set(
    evidence.filter((e) => e.kind === "probe_answer").map((e) => e.question_evidence_id || e.id),
  );
  return answers.size;
}

export function deriveStages(
  evidence: EvidenceItem[],
  assessments: RubricAssessment[],
  usedFullExplanation: boolean,
): StageState[] {
  const has = (kind: string) => evidence.some((e) => e.kind === kind);
  const pairs = probePairs(evidence);
  const probeDone = pairs >= 2;
  const transferDone = has("transfer_answer");
  const assessed = assessments.length > 0;
  const feedbackDone = assessed && assessments[assessments.length - 1].server_gate_result.passed;

  const blocked = usedFullExplanation;

  const stages: StageState[] = [
    { key: "explain", status: has("explanation") ? "done" : blocked ? "blocked" : "active", count: "" },
    {
      key: "probe",
      status: probeDone ? "done" : has("explanation") && !blocked ? "active" : blocked ? "blocked" : "todo",
      count: `${Math.min(pairs, 2)}/2`,
    },
    {
      key: "transfer",
      status: transferDone ? "done" : probeDone && !blocked ? "active" : blocked ? "blocked" : "todo",
      count: "",
    },
    {
      key: "feedback",
      status: feedbackDone ? "done" : transferDone && !blocked ? "active" : blocked ? "blocked" : "todo",
      count: "",
    },
  ];

  // After a full explanation every stage is reset to blocked/todo — the old
  // chain can never pass (§6.3).
  if (blocked) {
    stages[0] = { key: "explain", status: "blocked", count: "" };
    stages[1] = { key: "probe", status: "blocked", count: `${Math.min(pairs, 2)}/2` };
    stages[2] = { key: "transfer", status: "blocked", count: "" };
    stages[3] = { key: "feedback", status: "blocked", count: "" };
  }

  return stages;
}

/* ── Mastery projection display (§6.2, §7.5) ───────────────────────────── */

export function masteryDisplay(projection: KnowledgeProjection | null): MasteryDisplay {
  const state = projection?.mastery_state ?? "new";
  const review = projection?.review_state ?? "unscheduled";
  let tone: MasteryTone = "new";
  if (state === "in_progress") tone = "in-progress";
  else if (state === "needs_revision") tone = "revision";
  else if (state === "provisional_mastery") tone = "provisional";
  else if (state === "stable_mastery") tone = "stable";
  return {
    masteryState: state,
    reviewState: review,
    tone,
    nextReviewAt: projection?.next_review_at ?? null,
    activeAttemptId: projection?.active_attempt_id ?? "",
  };
}

/* ── Rubric (§6.4) ─────────────────────────────────────────────────────── */

export function rubricRows(assessment: RubricAssessment | null): RubricRow[] {
  if (!assessment) {
    return [
      { key: "correctness", labelKey: "rubric.correctness", score: 0, verdictKey: "unset" },
      { key: "completeness", labelKey: "rubric.completeness", score: 0, verdictKey: "unset" },
      { key: "causal_clarity", labelKey: "rubric.causalClarity", score: 0, verdictKey: "unset" },
      { key: "transfer", labelKey: "rubric.transfer", score: 0, verdictKey: "unset" },
    ];
  }
  const r = assessment.rubric;
  const verdict = (score: number): RubricRow["verdictKey"] =>
    score >= 2 ? "pass" : score >= 1 ? "partial" : "fail";
  return [
    { key: "correctness", labelKey: "rubric.correctness", score: r.correctness, verdictKey: verdict(r.correctness) },
    { key: "completeness", labelKey: "rubric.completeness", score: r.completeness, verdictKey: verdict(r.completeness) },
    { key: "causal_clarity", labelKey: "rubric.causalClarity", score: r.causal_clarity, verdictKey: verdict(r.causal_clarity) },
    { key: "transfer", labelKey: "rubric.transfer", score: r.transfer, verdictKey: verdict(r.transfer) },
  ];
}

/* ── Gaps (§7.4) ───────────────────────────────────────────────────────── */

export function activeGaps(gaps: GapRecord[]): GapRecord[] {
  return gaps
    .filter((g) => g.status === "active" || g.status === "reopened" || g.status === "improving")
    .sort((a, b) => a.priority - b.priority);
}

/* ── Conflicts (§7.7) ──────────────────────────────────────────────────── */

export function conflictSides(
  conflict: SourceConflict,
  snapshots: FeynmanMapPayload["source_snapshots"],
): WorkspaceConflict {
  const byId = new Map(snapshots.map((s) => [s.id, s]));
  const sides = conflict.source_snapshot_ids
    .map((id) => {
      const snapshot = byId.get(id);
      return snapshot
        ? { snapshot: { id: snapshot.id, title: snapshot.title, locator: snapshot.locator }, anchors: conflict.citation_anchors }
        : null;
    })
    .filter((s): s is WorkspaceConflict["sides"][number] => s !== null);
  return { conflict, sides, acceptedSideId: conflict.accepted_snapshot_id };
}

export function openConflicts(payload: FeynmanMapPayload): WorkspaceConflict[] {
  return payload.conflicts
    .filter((c) => c.status === "open")
    .map((c) => conflictSides(c, payload.source_snapshots));
}

/* ── Reviews (§13.2) ───────────────────────────────────────────────────── */

export function reviewTaskLabel(task: ReviewTask): string {
  return REVIEW_TASK_PRIORITY_LABEL[task.priority] ?? "low";
}

export function dueReviewTasks(reviews: ReviewTask[]): ReviewTask[] {
  return [...reviews].sort((a, b) => a.due_at - b.due_at);
}

/* ── Model identity (§7.6, §9.4, §13.3) ────────────────────────────────── */

export interface ModelIdentity {
  /** Teaching model is session-scoped and may switch; from chat state. */
  teaching: { label: string; protocol: string; raw: string } | null;
  /** Frozen evaluator snapshot on the attempt; never mutated by teaching switches. */
  evaluator: EvaluatorSnapshot | null;
}

export function evaluatorProtocol(snapshot: EvaluatorSnapshot | null): string {
  return snapshot?.resolved_api_protocol || snapshot?.requested_api_protocol || "";
}

export function protocolLabel(protocol: string): string {
  if (protocol === "openai_responses") return "OpenAI Responses";
  if (protocol === "openai_chat_completions") return "OpenAI Chat";
  if (protocol === "anthropic_messages") return "Anthropic Messages";
  return protocol || "auto";
}

/* ── Errors ────────────────────────────────────────────────────────────── */

export function toContractError(err: unknown): ContractError {
  const e = err as { status?: number; message?: string };
  const status = e?.status;
  const message = e?.message || "Request failed";
  if (status === 409 || status === 422) {
    return { kind: "recoverable", status, message };
  }
  return { kind: "fatal", status, message };
}

/** Pick the knowledge point the workspace should open first. */
export function initialKpId(
  payload: FeynmanMapPayload,
  preferred?: string | null,
): string {
  if (preferred && payload.map.modules.some((m) => m.knowledge_points.some((k) => k.id === preferred))) {
    return preferred;
  }
  const active = Object.keys(payload.active_attempts)[0];
  if (active) return active;
  const nextId = payload.next.knowledge_point_id;
  if (nextId) return nextId;
  for (const mod of payload.map.modules) {
    if (mod.knowledge_points.length) return mod.knowledge_points[0].id;
  }
  return "";
}

export function attemptDetailOf(attempt: AttemptDetail): AttemptDetail {
  return attempt;
}

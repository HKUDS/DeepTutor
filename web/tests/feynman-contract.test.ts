import test from "node:test";
import assert from "node:assert/strict";
import type {
  EvidenceItem,
  EvaluatorSnapshot,
  FeynmanMapPayload,
  GapRecord,
  RubricAssessment,
  SourceConflict,
} from "../lib/feynman-learning";
import {
  activeGaps,
  conflictSides,
  deriveStages,
  evaluatorProtocol,
  evidenceToConversation,
  initialKpId,
  masteryDisplay,
  openConflicts,
  protocolLabel,
  rubricRows,
  toContractError,
} from "../components/learning/contract";

function ev(partial: Partial<EvidenceItem> = {}): EvidenceItem {
  return {
    id: `ev-${Math.random()}`,
    attempt_id: "a1",
    chain_id: "c1",
    kind: "explanation",
    session_id: "s1",
    turn_id: "t1",
    message_id: "m1",
    event_seq: 0,
    input_mode: "text",
    transcript_confirmed: true,
    content_snapshot: "content",
    content_hash: "h",
    question_evidence_id: "",
    source_citations: [],
    help_level: null,
    created_at: 1000,
    ...partial,
  };
}

function assessment(partial: Partial<RubricAssessment> = {}): RubricAssessment {
  return {
    id: "as-1",
    attempt_id: "a1",
    revision: 1,
    assessment_sequence: 1,
    rubric: { correctness: 2, completeness: 1, causal_clarity: 1, transfer: 2 },
    critical_errors: [],
    strengths: [],
    gap_ids: [],
    evidence_ids: [],
    source_citations: [],
    evaluator_snapshot: null,
    model_invocation_id: "",
    supersedes_assessment_id: "",
    challenge_id: "",
    server_gate_result: {
      passed: true,
      required_evidence_kinds: [],
      missing_evidence_kinds: [],
      blocked_by_conflict: [],
      used_full_explanation: false,
      reasons: [],
    },
    created_at: 2000,
    ...partial,
  };
}

/* ── Conversation mapping (§7.2) ──────────────────────────────────────── */

test("evidenceToConversation maps kinds to roles and sorts by time", () => {
  const items = evidenceToConversation([
    ev({ id: "e2", kind: "probe_question", content_snapshot: "为什么?", created_at: 2000 }),
    ev({ id: "e1", kind: "explanation", content_snapshot: "我的讲解", created_at: 1000 }),
    ev({ id: "e3", kind: "probe_answer", content_snapshot: "因为…", created_at: 3000 }),
  ]);
  assert.deepEqual(
    items.map((i) => [i.role, i.content]),
    [
      ["user", "我的讲解"],
      ["assistant", "为什么?"],
      ["user", "因为…"],
    ],
  );
});

test("voice transcripts carry the confirmed boundary into the conversation", () => {
  const [item] = evidenceToConversation([
    ev({ kind: "explanation", input_mode: "voice_transcript", transcript_confirmed: true }),
  ]);
  assert.equal(item.inputMode, "voice_transcript");
  assert.equal(item.transcriptConfirmed, true);
});

/* ── Stages (§6.1) ────────────────────────────────────────────────────── */

test("deriveStages progresses explain → probe → transfer → feedback", () => {
  const stages = deriveStages(
    [
      ev({ kind: "explanation" }),
      ev({ kind: "probe_question", id: "pq1" }),
      ev({ kind: "probe_answer", question_evidence_id: "pq1" }),
      ev({ kind: "probe_question", id: "pq2" }),
      ev({ kind: "probe_answer", question_evidence_id: "pq2" }),
      ev({ kind: "transfer_question" }),
      ev({ kind: "transfer_answer" }),
    ],
    [assessment()],
    false,
  );
  assert.deepEqual(
    stages.map((s) => [s.key, s.status]),
    [
      ["explain", "done"],
      ["probe", "done"],
      ["transfer", "done"],
      ["feedback", "done"],
    ],
  );
});

test("deriveStages blocks every stage after a full explanation", () => {
  const stages = deriveStages(
    [ev({ kind: "explanation" }), ev({ kind: "probe_question", id: "pq1" })],
    [],
    true,
  );
  assert.ok(stages.every((s) => s.status === "blocked"));
});

test("probe count reads 1/2 until two distinct bound answers", () => {
  const stages = deriveStages(
    [
      ev({ kind: "explanation" }),
      ev({ kind: "probe_question", id: "pq1" }),
      ev({ kind: "probe_answer", question_evidence_id: "pq1" }),
    ],
    [],
    false,
  );
  assert.equal(stages[1].count, "1/2");
});

/* ── Mastery display (§6.2) ───────────────────────────────────────────── */

test("masteryDisplay maps orthogonal mastery/review projections", () => {
  const m = masteryDisplay({
    knowledge_point_id: "kp1",
    mastery_state: "provisional_mastery",
    review_state: "scheduled",
    active_attempt_id: "a1",
    latest_assessment_id: "",
    provisional_since: 1,
    stable_since: null,
    next_review_at: 2,
    updated_at: 3,
  });
  assert.equal(m.tone, "provisional");
  assert.equal(m.masteryState, "provisional_mastery");
  assert.equal(m.reviewState, "scheduled");
  assert.equal(m.nextReviewAt, 2);
});

test("masteryDisplay defaults to new without a projection", () => {
  assert.equal(masteryDisplay(null).tone, "new");
});

/* ── Rubric (§6.4) ────────────────────────────────────────────────────── */

test("rubricRows maps 0/1/2 scores to verdicts", () => {
  const rows = rubricRows(assessment());
  const byKey = Object.fromEntries(rows.map((r) => [r.key, r.verdictKey]));
  assert.equal(byKey.correctness, "pass");
  assert.equal(byKey.completeness, "partial");
  assert.equal(byKey.transfer, "pass");
});

test("rubricRows is all-unset without an assessment", () => {
  const rows = rubricRows(null);
  assert.ok(rows.every((r) => r.verdictKey === "unset"));
});

/* ── Gaps (§7.4) ──────────────────────────────────────────────────────── */

function gap(partial: Partial<GapRecord> = {}): GapRecord {
  return {
    id: "g1",
    knowledge_point_id: "kp1",
    label: "缺口",
    description: "",
    evidence_ids: [],
    source_citations: [],
    status: "active",
    priority: 1,
    first_seen_at: 1,
    last_seen_at: 1,
    resolved_at: null,
    ...partial,
  };
}

test("activeGaps drops resolved gaps and orders by priority", () => {
  const gaps = activeGaps([
    gap({ id: "g1", status: "resolved", priority: 0 }),
    gap({ id: "g2", priority: 5 }),
    gap({ id: "g3", priority: 1 }),
  ]);
  assert.deepEqual(gaps.map((g) => g.id), ["g3", "g2"]);
});

/* ── Conflicts (§7.7) ─────────────────────────────────────────────────── */

const MAP: FeynmanMapPayload = {
  book_id: "b1",
  next: {
    action: "assess",
    module_id: "m1",
    module_name: "M",
    knowledge_point_id: "kp2",
    knowledge_point_name: "K2",
    knowledge_point_type: "concept",
    status: "learning",
    gate: "qualitative",
    mastery: 0,
    threshold: 2,
    reason: "r",
    pending_prompt: "",
  },
  projections: {},
  active_attempts: {},
  evidence_summary: {},
  map_version: 2,
  map_version_id: "v2",
  source_snapshots: [
    { id: "s1", source_type: "user_material", material_id: "m", locator: "notes.md", title: "个人笔记", content_hash: "h1", citation_anchors: [], captured_at: 1 },
    { id: "s2", source_type: "web", material_id: "w", locator: "https://example.invalid/x", title: "外部补充", content_hash: "h2", citation_anchors: [], captured_at: 2 },
  ],
  map_versions: [],
  conflicts: [],
  updated_at: 3,
  map: {
    counts: { mastered: 0, learning: 1, new: 0, total: 1 },
    due_reviews: 0,
    complete: false,
    modules: [
      { id: "m1", name: "M", order: 0, mastered: 0, total: 1, knowledge_points: [{ id: "kp2", name: "K2", type: "concept", status: "learning", mastery: 0 }] },
    ],
  },
};

test("conflictSides keeps both sides of a conflict", () => {
  const conflict: SourceConflict = {
    id: "c1",
    path_id: "b1",
    knowledge_point_ids: ["kp2"],
    claim: "两处定义不一致",
    source_snapshot_ids: ["s1", "s2"],
    citation_anchors: ["§2", "p.18"],
    version: 1,
    status: "open",
    accepted_snapshot_id: "",
    resolution_note: "",
    resolved_at: null,
    resolved_by: "",
  };
  const sides = conflictSides(conflict, MAP.source_snapshots).sides;
  assert.equal(sides.length, 2);
  assert.deepEqual(sides.map((s) => s.snapshot.title), ["个人笔记", "外部补充"]);
});

test("openConflicts only exposes OPEN revisions", () => {
  const withConflicts: FeynmanMapPayload = {
    ...MAP,
    conflicts: [
      { id: "c1", path_id: "b1", knowledge_point_ids: [], claim: "open", source_snapshot_ids: ["s1"], citation_anchors: [], version: 1, status: "open", accepted_snapshot_id: "", resolution_note: "", resolved_at: null, resolved_by: "" },
      { id: "c2", path_id: "b1", knowledge_point_ids: [], claim: "resolved", source_snapshot_ids: ["s2"], citation_anchors: [], version: 1, status: "resolved", accepted_snapshot_id: "s2", resolution_note: "n", resolved_at: 1, resolved_by: "u" },
    ],
  };
  const open = openConflicts(withConflicts);
  assert.deepEqual(open.map((c) => c.conflict.id), ["c1"]);
});

test("initialKpId prefers active attempt, then next objective, then first", () => {
  assert.equal(
    initialKpId({ ...MAP, active_attempts: { kp2: { attempt_id: "a1", status: "collecting", cycle_type: "initial", chain_id: "c", map_version_id: "v2" } } }),
    "kp2",
  );
  assert.equal(initialKpId(MAP), "kp2");
  assert.equal(initialKpId({ ...MAP, next: { ...MAP.next, knowledge_point_id: "" } }), "kp2");
});

/* ── Model identity (§7.6, §13.3) ─────────────────────────────────────── */

test("protocolLabel covers the three explicit protocols", () => {
  assert.equal(protocolLabel("openai_responses"), "OpenAI Responses");
  assert.equal(protocolLabel("openai_chat_completions"), "OpenAI Chat");
  assert.equal(protocolLabel("anthropic_messages"), "Anthropic Messages");
  assert.equal(protocolLabel(""), "auto");
});

test("evaluatorProtocol prefers resolved over requested", () => {
  const snap: EvaluatorSnapshot = {
    profile_id: "p1",
    profile_name: "P",
    profile_revision: "1",
    requested_provider: "openai",
    requested_api_protocol: "auto",
    requested_model: "m",
    resolved_provider: "openai",
    resolved_api_protocol: "openai_responses",
    resolved_model: "m2",
    auto_resolution_reason: "explicit",
    base_url_fingerprint: "fp",
    strict_protocol: true,
    prompt_version: "",
    rubric_version: "",
    created_at: 1,
  };
  assert.equal(evaluatorProtocol(snap), "openai_responses");
});

/* ── Errors (§8.3) ────────────────────────────────────────────────────── */

test("toContractError classifies 409/422 as recoverable", () => {
  assert.equal(toContractError({ status: 409, message: "version conflict" }).kind, "recoverable");
  assert.equal(toContractError({ status: 422, message: "bad payload" }).kind, "recoverable");
  assert.equal(toContractError({ status: 500, message: "boom" }).kind, "fatal");
  assert.equal(toContractError(new Error("network")).kind, "fatal");
});

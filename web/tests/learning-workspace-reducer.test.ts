import test from "node:test";
import assert from "node:assert/strict";
import type { FeynmanMapPayload, ReviewsPayload } from "../lib/feynman-learning";
import {
  initialState,
  workspaceReducer,
  openConflictsFor,
  stagesFor,
  visibleConversation,
} from "../components/learning/workspaceReducer";

function mapPayload(overrides: Partial<FeynmanMapPayload> = {}): FeynmanMapPayload {
  return {
    book_id: "path-001",
    next: {
      action: "assess",
      module_id: "m1",
      module_name: "模块一",
      knowledge_point_id: "kp1",
      knowledge_point_name: "贝叶斯更新",
      knowledge_point_type: "concept",
      status: "learning",
      gate: "qualitative",
      mastery: 0,
      threshold: 2,
      reason: "需要解释",
      pending_prompt: "",
    },
    projections: {
      kp1: {
        knowledge_point_id: "kp1",
        mastery_state: "in_progress",
        review_state: "unscheduled",
        active_attempt_id: "att-1",
        latest_assessment_id: "",
        provisional_since: null,
        stable_since: null,
        next_review_at: null,
        updated_at: 1,
      },
    },
    active_attempts: {
      kp1: { attempt_id: "att-1", status: "collecting", cycle_type: "initial", chain_id: "chain-1", map_version_id: "v2" },
    },
    evidence_summary: { kp1: { count: 1, kinds: ["explanation"] } },
    map_version: 2,
    map_version_id: "v2",
    source_snapshots: [
      { id: "src-user-abc", source_type: "user_material", material_id: "mat-1", locator: "notes.md", title: "个人笔记", content_hash: "h1", citation_anchors: ["§2"], captured_at: 1 },
      { id: "src-web-def", source_type: "web", material_id: "web-1", locator: "https://example.invalid/x", title: "外部补充", content_hash: "h2", citation_anchors: [], captured_at: 2 },
    ],
    map_versions: [{ id: "v2", path_id: "path-001", version: 2, nodes: ["kp1"], edges: [], priorities: { kp1: 1 }, source_snapshot_ids: ["src-user-abc"], confirmed_at: 3 }],
    conflicts: [
      { id: "conflict-1", path_id: "path-001", knowledge_point_ids: ["kp1"], claim: "定义不一致", source_snapshot_ids: ["src-user-abc", "src-web-def"], citation_anchors: ["§2", "p.18"], version: 1, status: "open", accepted_snapshot_id: "", resolution_note: "", resolved_at: null, resolved_by: "" },
    ],
    updated_at: 4,
    map: {
      counts: { mastered: 0, learning: 1, new: 0, total: 1 },
      due_reviews: 0,
      complete: false,
      modules: [
        { id: "m1", name: "模块一", order: 0, mastered: 0, total: 1, knowledge_points: [{ id: "kp1", name: "贝叶斯更新", type: "concept", status: "learning", mastery: 0 }] },
      ],
    },
    ...overrides,
  };
}

function reviewsPayload(): ReviewsPayload {
  return {
    reviews: [],
    due_reviews: [],
    due_count: 0,
    needs_revision: [],
    updated_at: 4,
  };
}

function attemptDetail() {
  return {
    attempt: {
      id: "att-1",
      knowledge_point_id: "kp1",
      cycle_type: "initial",
      status: "collecting",
      invalidated_reason: "",
      knowledge_point_version: 1,
      map_version_id: "v2",
      source_snapshot_ids: ["src-user-abc"],
      supersedes_attempt_id: "",
      session_id: "path-001",
      started_turn_id: "turn-1",
      active_chain_id: "chain-1",
      max_help_level: "hint",
      evaluator_snapshot: {
        profile_id: "evaluator-profile-0001",
        profile_name: "评估模型",
        profile_revision: "rev-7",
        requested_provider: "openai",
        requested_api_protocol: "auto",
        requested_model: "gpt-5.6",
        resolved_provider: "openai",
        resolved_api_protocol: "openai_responses",
        resolved_model: "gpt-5.6",
        auto_resolution_reason: "explicit profile",
        base_url_fingerprint: "fp-abc123",
        strict_protocol: true,
        prompt_version: "pv-1",
        rubric_version: "rubric-v3",
        created_at: 1,
      },
      created_at: 1,
      updated_at: 2,
      closed_at: null,
    },
    evidence: [
      {
        id: "evidence-0000001",
        attempt_id: "att-1",
        chain_id: "chain-1",
        kind: "explanation",
        session_id: "path-001",
        turn_id: "turn-1",
        message_id: "msg-1",
        event_seq: 1,
        input_mode: "text",
        transcript_confirmed: true,
        content_snapshot: "贝叶斯更新是把先验与证据的解释力结合。",
        content_hash: "h-1",
        question_evidence_id: "",
        source_citations: [{ source_snapshot_id: "src-user-abc", anchor: "§2" }],
        help_level: null,
        created_at: 1,
      },
      {
        id: "evidence-0000002",
        attempt_id: "att-1",
        chain_id: "chain-1",
        kind: "probe_question",
        session_id: "path-001",
        turn_id: "turn-1",
        message_id: "msg-2",
        event_seq: 2,
        input_mode: "text",
        transcript_confirmed: true,
        content_snapshot: "阳性结果为什么不能直接说患病？",
        content_hash: "h-2",
        question_evidence_id: "",
        source_citations: [],
        help_level: null,
        created_at: 2,
      },
    ],
    assessments: [],
    gaps: [],
    challenges: [],
    audit: [],
    projection: {
      knowledge_point_id: "kp1",
      mastery_state: "in_progress",
      review_state: "unscheduled",
      active_attempt_id: "att-1",
      latest_assessment_id: "",
      provisional_since: null,
      stable_since: null,
      next_review_at: null,
      updated_at: 2,
    },
  };
}

/* ── Load / empty / error ─────────────────────────────────────────────── */

test("MAP_LOADED derives selected KP and stores refresh meta", () => {
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "path-001" });
  s = workspaceReducer(s, {
    type: "MAP_LOADED",
    map: mapPayload(),
    reviews: reviewsPayload(),
  });
  assert.equal(s.loadStatus, "ready");
  assert.equal(s.selectedKpId, "kp1");
  assert.equal(s.refreshMeta?.mapVersion, 2);
});

test("MAP_EMPTY surfaces the empty-path state", () => {
  const s = workspaceReducer(initialState, { type: "MAP_EMPTY" });
  assert.equal(s.loadStatus, "empty");
});

test("MAP_LOAD_FAILED sets a fatal error", () => {
  const s = workspaceReducer(initialState, {
    type: "MAP_LOAD_FAILED",
    error: { kind: "fatal", message: "boom" },
  });
  assert.equal(s.loadStatus, "error");
  assert.equal(s.fatalError, "boom");
});

/* ── Stale version recovery (§8.3) ────────────────────────────────────── */

test("recoverable ATTEMPT_LOAD_FAILED stores a recoverable error, RECOVER clears it", () => {
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "p" });
  s = workspaceReducer(s, { type: "MAP_LOADED", map: mapPayload(), reviews: reviewsPayload() });
  s = workspaceReducer(s, {
    type: "ATTEMPT_LOAD_FAILED",
    error: { kind: "recoverable", status: 409, message: "expected attempt version 1, current is 2" },
  });
  assert.equal(s.recoverableError?.status, 409);
  const recovered = workspaceReducer(s, { type: "RECOVER" });
  assert.equal(recovered.recoverableError, null);
});

test("CONFLICT_RESOLVED / CONFLICT_REOPENED track the action list", () => {
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "p" });
  s = workspaceReducer(s, { type: "MAP_LOADED", map: mapPayload(), reviews: reviewsPayload() });
  s = workspaceReducer(s, { type: "CONFLICT_RESOLVED", conflictId: "conflict-1" });
  assert.deepEqual(s.resolvedConflictIds, ["conflict-1"]);
  s = workspaceReducer(s, { type: "CONFLICT_REOPENED", conflictId: "conflict-1" });
  assert.deepEqual(s.reopenedConflictIds, ["conflict-1"]);
  assert.deepEqual(s.resolvedConflictIds, []);
});

/* ── Transcript editing boundary (§7.2, §13.1) ────────────────────────── */

test("TRANSCRIPT_START / CHANGED / CANCEL keep the editable boundary local", () => {
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "p" });
  s = workspaceReducer(s, { type: "TRANSCRIPT_START" });
  assert.equal(s.transcriptState, "editing");
  s = workspaceReducer(s, { type: "TRANSCRIPT_CHANGED", text: "灵敏度 vs 阳性预测值" });
  assert.equal(s.transcriptText, "灵敏度 vs 阳性预测值");
  // Still editing; confirming is a navigation concern, never local evidence.
  assert.equal(s.transcriptState, "editing");
  assert.equal(visibleConversation(s).length, 0);
  s = workspaceReducer(s, { type: "TRANSCRIPT_CANCEL" });
  assert.equal(s.transcriptState, "idle");
  assert.equal(s.transcriptText, "");
  assert.equal(visibleConversation(s).length, 0);
});

test("send / transcript-confirm / help no longer append local conversation items", () => {
  // The reducer has no SEND_MESSAGE / TRANSCRIPT_CONFIRM / REQUEST_HELP actions:
  // those flows store a handoff and navigate to the real chat, so a typed or
  // voice draft must never appear in the evidence-backed conversation stream.
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "p" });
  s = workspaceReducer(s, { type: "MAP_LOADED", map: mapPayload(), reviews: reviewsPayload() });
  s = workspaceReducer(s, { type: "ATTEMPT_LOADED", attempt: attemptDetail() });
  const before = visibleConversation(s);
  assert.ok(before.length > 0, "fixture carries server evidence");

  s = workspaceReducer(s, { type: "COMPOSER_CHANGED", text: "我的讲解草稿" });
  s = workspaceReducer(s, { type: "TRANSCRIPT_START" });
  s = workspaceReducer(s, { type: "TRANSCRIPT_CHANGED", text: "语音草稿" });
  // Tab switches and conflict toggles must not fabricate evidence either.
  s = workspaceReducer(s, { type: "TAB_CHANGED", tab: "map" });
  s = workspaceReducer(s, { type: "CONFLICT_RESOLVED", conflictId: "conflict-1" });

  const after = visibleConversation(s);
  assert.deepEqual(
    after.map((i) => i.key),
    before.map((i) => i.key),
    "conversation stream still reflects only server evidence",
  );
  assert.equal(after.some((i) => i.kind === "pending"), false);
});

/* ── Model identities (§7.6, §13.3) ───────────────────────────────────── */

test("ATTEMPT_LOADED surfaces the frozen evaluator snapshot and help level", () => {
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "p" });
  s = workspaceReducer(s, { type: "MAP_LOADED", map: mapPayload(), reviews: reviewsPayload() });
  s = workspaceReducer(s, { type: "ATTEMPT_LOADED", attempt: attemptDetail() });
  assert.equal(s.attempt?.attempt.evaluator_snapshot?.resolved_api_protocol, "openai_responses");
  assert.equal(s.helpLevel, "hint");
  assert.equal(s.usedFullExplanation, false);
});

test("full explanation on the attempt (server read) flags the chain closed", () => {
  const fullHelp = attemptDetail();
  fullHelp.attempt.max_help_level = "full_explanation";
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "p" });
  s = workspaceReducer(s, { type: "MAP_LOADED", map: mapPayload(), reviews: reviewsPayload() });
  s = workspaceReducer(s, { type: "ATTEMPT_LOADED", attempt: fullHelp });
  assert.equal(s.usedFullExplanation, true);
  assert.equal(s.helpLevel, "full_explanation");
  const stages = stagesFor(s);
  assert.ok(stages.every((st) => st.status === "blocked"));
});

/* ── Mobile tabs ──────────────────────────────────────────────────────── */

test("TAB_CHANGED switches the mobile view and preserves state", () => {
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "p" });
  s = workspaceReducer(s, { type: "MAP_LOADED", map: mapPayload(), reviews: reviewsPayload() });
  s = workspaceReducer(s, { type: "COMPOSER_CHANGED", text: "草稿" });
  s = workspaceReducer(s, { type: "TAB_CHANGED", tab: "map" });
  assert.equal(s.activeTab, "map");
  s = workspaceReducer(s, { type: "TAB_CHANGED", tab: "evidence" });
  assert.equal(s.activeTab, "evidence");
  // Key session state (composer draft) survives tab switches, but no local
  // conversation item is ever appended.
  assert.equal(s.composerText, "草稿");
  assert.equal(visibleConversation(s).length, 0);
});

/* ── Conflict/gap state (§7.7) ────────────────────────────────────────── */

test("openConflictsFor keeps both sides of open conflicts", () => {
  let s = workspaceReducer(initialState, { type: "INIT", pathId: "p" });
  s = workspaceReducer(s, { type: "MAP_LOADED", map: mapPayload(), reviews: reviewsPayload() });
  const open = openConflictsFor(s);
  assert.equal(open.length, 1);
  assert.equal(open[0].sides.length, 2);
  assert.deepEqual(
    open[0].sides.map((side) => side.snapshot.id),
    ["src-user-abc", "src-web-def"],
  );
});

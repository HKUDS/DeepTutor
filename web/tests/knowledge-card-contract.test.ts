import test from "node:test";
import assert from "node:assert/strict";
import type { KnowledgeCardGenerationAttempt, KnowledgeCardView } from "../lib/knowledge-card-api";
import type { KnowledgeBaseSummary } from "../lib/knowledge-api";
import {
  anyWritableKb,
  cardActions,
  classifyKbs,
  failureAssurance,
  generationSurface,
  kbDisableReason,
  mergeMutationResult,
  pendingCards,
} from "../components/learning/knowledgeCard";

function card(overrides: Partial<KnowledgeCardView> = {}): KnowledgeCardView {
  return {
    card_id: "card-1",
    knowledge_point_id: "kp1",
    status: "draft",
    revision: 1,
    version: 0,
    generation_locked_by_user_edit: false,
    draft_generation_status: "queued",
    title: "",
    body: "",
    content_hash: "h",
    source_snapshot_ids: ["s1"],
    evidence_ids: ["ev1"],
    artifact_ids: [],
    source_count: 1,
    evidence_count: 1,
    artifact_count: 0,
    stable_assessment_id: "ra1",
    stable_assessment_sequence: 1,
    target_kb_name: null,
    document_rel_path: null,
    document_sha256: null,
    publication_key: null,
    quarantine_rel_path: null,
    retraction_request_id: null,
    retraction_operation_id: null,
    cleanup_status: "",
    cleanup_error: null,
    confirmed_at: null,
    published_at: null,
    stale_at: null,
    retracted_at: null,
    error_code: null,
    sanitized_error: null,
    latest_generation_attempt: null,
    model_identity: null,
    sources: [],
    artifacts: [],
    occupies_slot: true,
    ...overrides,
  };
}

function kb(overrides: Partial<KnowledgeBaseSummary> = {}): KnowledgeBaseSummary {
  return { name: "kb", status: "ready", ...overrides };
}

function attempt(status: string): KnowledgeCardGenerationAttempt {
  return {
    id: "att-1",
    status,
    generation_attempt_no: 1,
    retry_of_generation_attempt_id: null,
    input_card_revision: 1,
    model_invocation_id: null,
    output_hash: null,
    error_code: null,
    sanitized_error: null,
    created_at: null,
    started_at: null,
    finished_at: null,
  };
}

/* ── pending filter ────────────────────────────────────────────────────── */

test("pendingCards excludes discarded and retracted, keeps everything else", () => {
  const cards = [
    card({ card_id: "a", status: "draft" }),
    card({ card_id: "b", status: "published" }),
    card({ card_id: "c", status: "discarded" }),
    card({ card_id: "d", status: "retracted" }),
    card({ card_id: "e", status: "stale_evidence" }),
  ];
  assert.deepEqual(
    pendingCards(cards).map((c) => c.card_id),
    ["a", "b", "e"],
  );
});

/* ── KB writability classification (§13.5, §8.5) ───────────────────────── */

test("kbDisableReason classifies connected/assigned/read-only/error/indexing/needs-reindex", () => {
  assert.equal(kbDisableReason(kb({ metadata: { type: "obsidian" }, status: "connected" })), "connected");
  assert.equal(kbDisableReason(kb({ metadata: { type: "linked" } })), "connected");
  assert.equal(kbDisableReason(kb({ metadata: { type: "lightrag_server" } })), "connected");
  assert.equal(kbDisableReason(kb({ assigned: true, read_only: true })), "assigned");
  assert.equal(kbDisableReason(kb({ read_only: true })), "read_only");
  assert.equal(kbDisableReason(kb({ available: false })), "unavailable");
  assert.equal(kbDisableReason(kb({ status: "error" })), "error");
  assert.equal(kbDisableReason(kb({ status: "indexing" })), "indexing");
  assert.equal(kbDisableReason(kb({ status: "processing" })), "indexing");
  assert.equal(kbDisableReason(kb({ status: "needs_reindex" })), "needs_reindex");
  assert.equal(kbDisableReason(kb({ metadata: { needs_reindex: true } })), "needs_reindex");
  // A local owned ready KB is the only writable target.
  assert.equal(kbDisableReason(kb({ status: "ready" })), null);
});

test("classifyKbs sorts writable first and keeps disabled entries visible", () => {
  const options = classifyKbs([
    kb({ name: "团队网络原理", status: "ready", metadata: { type: "linked" } }),
    kb({ name: "我的学习知识库", status: "ready" }),
    kb({ name: "课程公共库", status: "error" }),
  ]);
  assert.deepEqual(
    options.map((o) => o.name),
    ["我的学习知识库", "团队网络原理", "课程公共库"],
  );
  assert.equal(options[0].writable, true);
  assert.equal(options[1].disableReason, "connected");
  assert.equal(anyWritableKb(options), true);
});

test("anyWritableKb is false when every KB is disabled", () => {
  assert.equal(anyWritableKb(classifyKbs([kb({ status: "error" }), kb({ metadata: { type: "obsidian" } })])), false);
});

/* ── action availability by status (§13.5, §15) ───────────────────────── */

test("draft is editable, publishable and discardable; retry only after a terminated attempt", () => {
  const a = cardActions(card());
  assert.equal(a.canEdit, true);
  assert.equal(a.canSaveDraft, true);
  assert.equal(a.canPublish, true);
  assert.equal(a.canDiscard, true);
  assert.equal(a.canRetract, false);
  assert.equal(a.canRetryGeneration, false); // no attempt yet
});

test("generation retry requires an un-locked draft with a failed/unknown attempt", () => {
  assert.equal(
    cardActions(card({ latest_generation_attempt: attempt("failed") })).canRetryGeneration,
    true,
  );
  assert.equal(
    cardActions(card({ latest_generation_attempt: attempt("unknown") })).canRetryGeneration,
    true,
  );
  assert.equal(
    cardActions(card({ latest_generation_attempt: attempt("queued") })).canRetryGeneration,
    false,
  );
  assert.equal(
    cardActions(
      card({
        generation_locked_by_user_edit: true,
        latest_generation_attempt: attempt("failed"),
      }),
    ).canRetryGeneration,
    false,
  );
});

test("stale_evidence is read-only but discardable", () => {
  const a = cardActions(card({ status: "stale_evidence" }));
  assert.equal(a.canEdit, false);
  assert.equal(a.canPublish, false);
  assert.equal(a.canRetryGeneration, false);
  assert.equal(a.canDiscard, true);
});

test("published allows retract only; publish_failed allows retry-publish only", () => {
  const published = cardActions(card({ status: "published" }));
  assert.equal(published.canRetract, true);
  assert.equal(published.canEdit, false);
  assert.equal(published.canDiscard, false);

  const failed = cardActions(card({ status: "publish_failed" }));
  assert.equal(failed.canRetryPublish, true);
  assert.equal(failed.canEdit, false);
  assert.equal(failed.canPublish, true);
});

test("reconcile states expose explicit repair actions", () => {
  assert.equal(cardActions(card({ status: "reconcile_required" })).canReconcilePublication, true);
  assert.equal(cardActions(card({ status: "retract_reconcile_required" })).canReconcileRetraction, true);
  assert.equal(cardActions(card({ status: "retracting" })).canRetract, false);
});

/* ── failure assurances / generation surface ───────────────────────────── */

test("failureAssurance returns the exact recovery surface", () => {
  assert.deepEqual(failureAssurance(card({ status: "publish_failed" })), { kind: "publish_failed" });
  assert.deepEqual(failureAssurance(card({ status: "reconcile_required" })), { kind: "reconcile_required" });
  assert.deepEqual(failureAssurance(card({ status: "retract_reconcile_required" })), { kind: "retract_reconcile_required" });
  assert.equal(failureAssurance(card({ status: "draft" })), null);
});

test("generationSurface maps attempt status to a render surface", () => {
  assert.equal(generationSurface(card()), "none");
  assert.equal(generationSurface(card({ latest_generation_attempt: attempt("queued") })), "queued");
  assert.equal(generationSurface(card({ latest_generation_attempt: attempt("running") })), "running");
  assert.equal(generationSurface(card({ latest_generation_attempt: attempt("succeeded") })), "ready");
  assert.equal(generationSurface(card({ latest_generation_attempt: attempt("superseded_by_edit") })), "superseded_by_edit");
});

/* ── mutation result merge ─────────────────────────────────────────────── */

test("mergeMutationResult folds a KB-03/KB-04 projection onto the full card", () => {
  const merged = mergeMutationResult(card({ title: "t" }), {
    card_id: "card-1",
    status: "published",
    replayed: false,
    revision: 2,
    target_kb_name: "我的学习知识库",
    document_rel_path: "learning_cards/card-1-v2.md",
    document_sha256: "sha",
    publication_key: "key",
    quarantine_rel_path: null,
    retraction_request_id: null,
    retraction_operation_id: null,
    confirmed_at: null,
    published_at: 123,
    retracted_at: null,
    cleanup_status: "",
    cleanup_error: null,
    error_code: null,
    sanitized_error: null,
  });
  assert.equal(merged.status, "published");
  assert.equal(merged.revision, 2);
  assert.equal(merged.title, "t");
  assert.equal(merged.target_kb_name, "我的学习知识库");
  assert.equal(merged.published_at, 123);
});
